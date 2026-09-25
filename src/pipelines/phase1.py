from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings, load_settings
from core.utils import ensure_parent, now_utc, read_json, write_csv
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.agent import run_agent_demo
from retrieval.index import LocalEmbeddingIndex

AGENT_DEMO_QUESTIONS = 3


def write_frame(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    write_csv(df, csv_path)
    ensure_parent(json_path)
    json_path.write_text(df.to_json(orient="records", force_ascii=False, indent=2) + "\n", encoding="utf-8")


def print_metrics(title: str, metrics: dict[str, Any]) -> None:
    print(f"\n{title}")
    for key in ("samples", "retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score"):
        value = metrics.get(key)
        numeric = isinstance(value, (int, float)) and key != "samples"
        print(f"  {key:20} {value:.3f}" if numeric else f"  {key:20} {value}")


def _load_or_build_test_set(df: pd.DataFrame, settings: Settings) -> list[dict[str, Any]]:
    path = settings.paths.eval_testset
    if path.exists() and not settings.refresh_test_set:
        test_set = read_json(path)
        known = set(df["paper_id"])
        if all(doc_id in known for item in test_set for doc_id in item["ground_truth_doc_ids"]):
            print(f"[test set] Reusing {path.name} ({len(test_set)} questions); set REFRESH_TEST_SET=1 to rebuild.")
            return test_set
        print(f"[test set] {path.name} references papers missing from the clean data; rebuilding.")
    test_set = build_test_set(df, path)
    print(f"[test set] Built {len(test_set)} questions -> {path.name}")
    return test_set


def main() -> None:
    settings = load_settings()
    run_date = now_utc()
    paths = settings.paths

    records = fetch_source_records(settings)
    df = build_clean_dataframe(records, run_date)
    write_frame(df, paths.clean_csv, paths.clean_json)
    print(f"[clean] {len(records)} raw records -> {len(df)} clean rows")

    quality = run_data_quality_checks(df, settings, "baseline")
    freshness = build_freshness_report(df, settings, paths.freshness_report)
    if not quality["success"]:
        failed = [f"{item['expectation']}({item['column'] or 'table'})" for item in quality["expectations"] if not item["success"]]
        raise SystemExit(
            f"[quality gate] Baseline data failed GX checks: {', '.join(failed)}. "
            f"Not indexing bad data; see {paths.baseline_quality_report}."
        )
    print(f"[quality gate] GX passed; freshness stale_ratio={freshness['stale_ratio']:.3f} is_fresh={freshness['is_fresh']}")
    if not freshness["is_fresh"]:
        print("[freshness] WARNING: stale ratio exceeds the SLA; refresh the source soon.")

    index = LocalEmbeddingIndex.build(df, settings, paths.embeddings_json)
    print(f"[index] Collection {index.collection_name} holds {index.collection.count()} documents")

    test_set = _load_or_build_test_set(df, settings)
    bundle = evaluate_pipeline(settings, index, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers)

    source_summary = {
        "source_api": settings.source_api,
        "mode": "live" if settings.refresh_source else "snapshot",
        "query": settings.source_query,
        "raw_records": len(records),
        "clean_rows": len(df),
        "run_date": run_date.isoformat(timespec="seconds"),
    }
    generate_phase1_report(paths.baseline_report, source_summary, bundle.summary, quality, freshness)

    demo = run_agent_demo(
        settings, index, [item["question"] for item in test_set[:AGENT_DEMO_QUESTIONS]], paths.demo_answers
    )
    statuses = ", ".join(sorted({row["status"] for row in demo}))
    print(f"[agent demo] {len(demo)} questions via {settings.llm_provider}: {statuses}")

    print_metrics("Baseline metrics", bundle.summary)
    print(f"\nReport: {paths.baseline_report}")
