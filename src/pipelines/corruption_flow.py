from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import now_utc, read_json
from evaluation.metrics import evaluate_pipeline
from ingestion.corruption import corrupt_clean_dataframe
from ingestion.repair import repair_from_raw
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_corruption_report
from pipelines.phase1 import write_frame
from retrieval.index import LocalEmbeddingIndex

METRIC_KEYS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score")


def _require(path: Path) -> Path:
    if not path.exists():
        raise SystemExit(f"Missing {path}. Run `python script/run_phase1.py` first.")
    return path


def _check(settings: Settings, df: pd.DataFrame, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    quality = run_data_quality_checks(df, settings, name)
    freshness = build_freshness_report(df, settings, settings.paths.quality_dir / f"freshness_report_{name}.json")
    failed = [f"{item['expectation']}({item['column'] or 'table'})" for item in quality["expectations"] if not item["success"]]
    gate = "PASS" if quality["success"] else f"FAIL -> {', '.join(failed)}"
    print(f"[{name}] GX {gate}; stale_ratio={freshness['stale_ratio']:.3f} is_fresh={freshness['is_fresh']}")
    return quality, freshness


def _evaluate(settings: Settings, df: pd.DataFrame, embeddings: Path, metrics: Path, answers: Path) -> dict[str, Any]:
    index = LocalEmbeddingIndex.build(df, settings, embeddings)
    bundle = evaluate_pipeline(settings, index, settings.paths.eval_testset, metrics, answers)
    print(f"[index] {index.collection_name}: {index.collection.count()} documents evaluated")
    return {**bundle.summary, "answers": bundle.answers}


def _print_comparison(baseline: dict[str, Any], corrupted: dict[str, Any], repaired: dict[str, Any]) -> None:
    print(f"\n{'metric':22}{'baseline':>10}{'corrupted':>11}{'repaired':>10}")
    for key in METRIC_KEYS:
        print(f"{key:22}{baseline[key]:>10.3f}{corrupted[key]:>11.3f}{repaired[key]:>10.3f}")


def main() -> None:
    settings = load_settings()
    run_date = now_utc()
    paths = settings.paths

    baseline = read_json(_require(paths.baseline_metrics))
    _require(paths.eval_testset)
    if paths.baseline_answers.exists():
        baseline["answers"] = read_json(paths.baseline_answers)
    clean = pd.DataFrame(read_json(_require(paths.clean_json)))

    corrupted_df = corrupt_clean_dataframe(clean, paths.corruption_log)
    write_frame(corrupted_df, paths.corrupted_clean_csv, paths.corrupted_clean_json)
    print(f"[corrupt] {len(clean)} clean rows -> {len(corrupted_df)} corrupted rows; log: {paths.corruption_log.name}")
    corrupted_quality, corrupted_freshness = _check(settings, corrupted_df, "corrupted")
    if not corrupted_quality["success"] or not corrupted_freshness["is_fresh"]:
        print("[corrupted] WARNING: quality gate would block this data; indexing anyway to measure the silent failure.")
    corrupted = _evaluate(
        settings, corrupted_df, paths.corrupted_embeddings_json, paths.corrupted_metrics, paths.corrupted_answers
    )

    repaired_df = repair_from_raw(settings, run_date)
    print(f"[repair] Rebuilt {len(repaired_df)} rows from {paths.raw_records_json.name}")
    repaired_quality, repaired_freshness = _check(settings, repaired_df, "repaired")
    repaired = _evaluate(
        settings, repaired_df, paths.repaired_embeddings_json, paths.repaired_metrics, paths.repaired_answers
    )

    generate_corruption_report(
        paths.comparison_report,
        baseline,
        corrupted,
        repaired,
        corrupted_quality,
        repaired_quality,
        corrupted_freshness,
        repaired_freshness,
    )
    _print_comparison(baseline, corrupted, repaired)
    print(f"\nReport: {paths.comparison_report}")
