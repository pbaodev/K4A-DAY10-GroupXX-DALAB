from __future__ import annotations

import hashlib
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json
from evaluation.metrics import evaluate_pipeline
from ingestion.cleaning import build_clean_dataframe
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.crossref import load_raw_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from pipelines.phase1 import load_clean_dataframe, save_clean_artifacts
from retrieval.index import LocalEmbeddingIndex

COMPARED_METRICS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score")


def _fingerprint(df: pd.DataFrame) -> str:
    payload = df.to_json(orient="records", force_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _content_fingerprint(df: pd.DataFrame) -> str:
    # age_days depends on the run date, so compare the served content without it.
    return _fingerprint(df.drop(columns=["age_days"], errors="ignore").reset_index(drop=True))


def _repair_from_raw(settings: Settings, run_date) -> pd.DataFrame:
    """Idempotent repair: rebuild the clean corpus from the immutable raw snapshot, never from the broken data."""
    return build_clean_dataframe(load_raw_records(settings.paths.raw_records_json), run_date)


def _evaluate_state(settings: Settings, df: pd.DataFrame, embeddings_path, metrics_path, answers_path, label: str):
    index = LocalEmbeddingIndex.build(df, settings, embeddings_path)
    print(f"[phase2]     indexed {index.collection.count()} vectors into '{index.collection_name}', evaluating {label}...")
    return evaluate_pipeline(settings, index, settings.paths.eval_testset, metrics_path, answers_path)


def _print_comparison(baseline: dict[str, Any], corrupted: dict[str, Any], repaired: dict[str, Any]) -> None:
    print("\n=== Baseline vs Corrupted vs Repaired ===")
    print(f"{'metric':<22}{'baseline':>12}{'corrupted':>12}{'repaired':>12}")
    for key in COMPARED_METRICS:
        print(f"{key:<22}{baseline[key]:>12.4f}{corrupted[key]:>12.4f}{repaired[key]:>12.4f}")


def main() -> None:
    settings = load_settings()
    paths = settings.paths
    run_date = now_utc()

    print("[phase2] 1/6 Loading baseline artifacts...")
    for required in (paths.clean_json, paths.baseline_metrics, paths.eval_testset):
        if not required.exists():
            raise FileNotFoundError(f"Missing {required.relative_to(paths.project_dir)}; run script/run_phase1.py first.")
    clean_df = load_clean_dataframe(paths.clean_json)
    baseline_metrics = read_json(paths.baseline_metrics)
    baseline_quality = read_json(paths.baseline_quality_report) if paths.baseline_quality_report.exists() else None

    print("[phase2] 2/6 Injecting 6 corruption types...")
    corrupted_df = corrupt_clean_dataframe(clean_df, paths.corruption_log)
    save_clean_artifacts(corrupted_df, paths.corrupted_clean_csv, paths.corrupted_clean_json)
    corruption_log = read_json(paths.corruption_log)
    print(f"[phase2]     {corruption_log['rows_before']} -> {corruption_log['rows_after']} rows, log -> {paths.corruption_log.name}")

    print("[phase2] 3/6 Quality gate on corrupted data...")
    corrupted_quality = run_data_quality_checks(corrupted_df, settings, "corrupted")
    corrupted_freshness = build_freshness_report(
        corrupted_df, settings, paths.quality_dir / "corrupted_freshness_report.json"
    )
    print(
        f"[phase2]     GX success={corrupted_quality['success']} failed={corrupted_quality['failed_expectations']}, "
        f"is_fresh={corrupted_freshness['is_fresh']} (stale ratio {corrupted_freshness['stale_ratio']})"
    )

    # In production a failed gate would block serving. Here we index the corrupted data anyway,
    # in its own collection, to measure the silent failure the gate protects us from.
    print("[phase2] 4/6 Measuring degradation on corrupted index (gate bypassed on purpose)...")
    corrupted_bundle = _evaluate_state(
        settings, corrupted_df, paths.corrupted_embeddings_json, paths.corrupted_metrics, paths.corrupted_answers, "corrupted"
    )

    gate_failed = not corrupted_quality["gate_passed"]
    trigger = (
        "auto: quality gate failed (" + ", ".join(corrupted_quality["failed_expectations"] or ["freshness SLA"]) + ")"
        if gate_failed
        else "manual: gate passed, repair run to prove idempotency"
    )
    print(f"[phase2] 5/6 Repairing from raw snapshot [{trigger}]...")
    repaired_df = _repair_from_raw(settings, run_date)
    second_run_df = _repair_from_raw(settings, run_date)
    save_clean_artifacts(repaired_df, paths.repaired_clean_csv, paths.repaired_clean_json)
    repaired_quality = run_data_quality_checks(repaired_df, settings, "repaired")
    repaired_freshness = build_freshness_report(repaired_df, settings, paths.quality_dir / "repaired_freshness_report.json")
    repaired_bundle = _evaluate_state(
        settings, repaired_df, paths.repaired_embeddings_json, paths.repaired_metrics, paths.repaired_answers, "repaired"
    )

    repair_summary = {
        "trigger": trigger,
        "source": "data/raw/crossref_records.json (immutable raw snapshot)",
        "repaired_rows": len(repaired_df),
        "idempotent (2 repair runs identical)": _fingerprint(repaired_df) == _fingerprint(second_run_df),
        "content matches baseline clean data": _content_fingerprint(repaired_df) == _content_fingerprint(clean_df),
        "repaired GX success": repaired_quality["success"],
        "repaired is_fresh": repaired_freshness["is_fresh"],
        "repaired sha256": _fingerprint(repaired_df)[:16],
    }
    for key, value in repair_summary.items():
        print(f"[phase2]     {key}: {value}")

    print("[phase2] 6/6 Writing comparison report...")
    generate_corruption_report(
        paths.comparison_report,
        baseline_metrics,
        corrupted_bundle.summary,
        repaired_bundle.summary,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
        corruption_log=corruption_log,
        repair_summary=repair_summary,
        answers_by_state={
            "baseline": read_json(paths.baseline_answers) if paths.baseline_answers.exists() else [],
            "corrupted": corrupted_bundle.answers,
            "repaired": repaired_bundle.answers,
        },
        baseline_quality=baseline_quality,
    )

    _print_comparison(baseline_metrics, corrupted_bundle.summary, repaired_bundle.summary)
    print(f"\nReport: {paths.comparison_report.relative_to(paths.project_dir)}")
    if not repair_summary["idempotent (2 repair runs identical)"]:
        raise RuntimeError("Repair is not idempotent: two runs from the same raw snapshot differ.")
