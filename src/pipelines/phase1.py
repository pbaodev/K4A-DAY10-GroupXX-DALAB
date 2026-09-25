from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from core.config import Settings, load_settings, normalized_provider
from core.utils import now_utc, read_json, write_csv, write_json
from evaluation.metrics import evaluate_pipeline
from evaluation.testset import build_test_set
from ingestion.cleaning import build_clean_dataframe
from ingestion.crossref import fetch_source_records
from observability.quality import build_freshness_report, run_data_quality_checks
from observability.reporting import generate_phase1_report
from retrieval.index import LocalEmbeddingIndex

LIST_COLUMNS = ("authors", "categories")
DEMO_QUESTIONS = [
    "Which papers in the corpus discuss data quality gates or data observability for RAG?",
    "Who authored the paper about freshness SLAs for real-time LLM knowledge augmentation?",
]


def save_clean_artifacts(df: pd.DataFrame, csv_path: Path, json_path: Path) -> None:
    """Persist a clean dataframe: JSON keeps list columns as lists, CSV joins them for readability."""
    write_json(json_path, json.loads(df.to_json(orient="records", force_ascii=False)))
    csv_frame = df.copy()
    for column in LIST_COLUMNS:
        if column in csv_frame:
            csv_frame[column] = csv_frame[column].apply(lambda values: "; ".join(values or []))
    write_csv(csv_frame, csv_path)


def load_clean_dataframe(json_path: Path) -> pd.DataFrame:
    return pd.DataFrame(read_json(json_path))


def _load_or_build_test_set(df: pd.DataFrame, settings: Settings) -> list[dict[str, Any]]:
    path = settings.paths.eval_testset
    if path.exists() and not (settings.refresh_test_set or settings.refresh_source):
        test_set = read_json(path)
        known_ids = set(df["paper_id"])
        if test_set and all(doc_id in known_ids for item in test_set for doc_id in item["ground_truth_doc_ids"]):
            print(f"[phase1] Reusing fixed test set ({len(test_set)} questions) from {path.name}.")
            return test_set
        print("[phase1] Existing test set references unknown papers; rebuilding it.")
    test_set = build_test_set(df, path)
    print(f"[phase1] Built test set with {len(test_set)} questions.")
    return test_set


def _message_text(content: Any) -> str:
    # Some providers (e.g. Gemini) return a list of content blocks instead of a plain string.
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block) for block in content
        ).strip()
    return str(content)


def _run_agent_demo(settings: Settings, index: LocalEmbeddingIndex) -> None:
    """Optional tool-calling agent demo; never blocks the pipeline if the LLM is unavailable."""
    try:
        from retrieval.agent import build_agent, run_agent_question

        agent = build_agent(settings, index)
        answers = [
            {"question": question, "answer": _message_text(run_agent_question(agent, question))}
            for question in DEMO_QUESTIONS
        ]
        payload = {"provider": normalized_provider(settings), "model": settings.model_name, "answers": answers}
        print(f"[phase1] Agent demo answered {len(answers)} questions.")
    except Exception as exc:  # noqa: BLE001 - demo only
        payload = {"provider": normalized_provider(settings), "model": settings.model_name, "error": str(exc)}
        print(f"[phase1] Agent demo skipped: {exc.__class__.__name__}: {str(exc)[:160]}")
    write_json(settings.paths.demo_answers, payload)


def main() -> None:
    settings = load_settings()
    paths = settings.paths
    run_date = now_utc()

    print("[phase1] 1/7 Ingesting source records...")
    records = fetch_source_records(settings)
    print(f"[phase1]     {len(records)} raw records -> {paths.raw_records_json.name}")

    print("[phase1] 2/7 Cleaning...")
    df = build_clean_dataframe(records, run_date)
    save_clean_artifacts(df, paths.clean_csv, paths.clean_json)
    print(f"[phase1]     {len(df)} clean rows -> {paths.clean_csv.name}, {paths.clean_json.name}")

    print("[phase1] 3/7 Quality gate (Great Expectations 1.x + freshness)...")
    quality = run_data_quality_checks(df, settings, "baseline")
    freshness = build_freshness_report(df, settings, paths.freshness_report)
    print(
        f"[phase1]     GX success={quality['success']} "
        f"({quality['successful_expectations']}/{quality['evaluated_expectations']}), "
        f"is_fresh={freshness['is_fresh']} (stale {freshness['stale_rows']}/{freshness['total_rows']})"
    )
    if not quality["success"]:
        raise RuntimeError(
            "Quality gate failed on baseline data, refusing to index: "
            + ", ".join(quality["failed_expectations"])
        )
    if not freshness["is_fresh"]:
        print("[phase1]     WARNING: freshness SLA breached, corpus should be refreshed (REFRESH_SOURCE=1).")

    print(f"[phase1] 4/7 Indexing into ChromaDB collection '{settings.baseline_collection_name}'...")
    index = LocalEmbeddingIndex.build(df, settings, paths.embeddings_json)
    print(f"[phase1]     {index.collection.count()} vectors indexed with {settings.embedding_model}")

    print("[phase1] 5/7 Preparing benchmark test set...")
    _load_or_build_test_set(df, settings)

    print(f"[phase1] 6/7 Evaluating baseline (LLM judge provider: {normalized_provider(settings)})...")
    bundle = evaluate_pipeline(settings, index, paths.eval_testset, paths.baseline_metrics, paths.baseline_answers)
    metrics = bundle.summary

    print("[phase1] 7/7 Writing report and running agent demo...")
    source_summary = {
        "Source": settings.source_api,
        "Mode": "live API" if settings.refresh_source else "offline snapshot",
        "Query": settings.source_query,
        "Raw response": "data/raw/crossref_response.json",
        "Raw records": f"data/raw/crossref_records.json ({len(records)} records)",
        "Clean rows": len(df),
        "Run date (UTC)": run_date.date().isoformat(),
        "Embedding model": settings.embedding_model,
        "Chroma collection": f"{settings.baseline_collection_name} ({index.collection.count()} vectors)",
        "Top-k": settings.top_k,
    }
    generate_phase1_report(paths.baseline_report, source_summary, metrics, quality, freshness, answers=bundle.answers)
    _run_agent_demo(settings, index)

    print("\n=== Baseline metrics ===")
    for key in ("samples", "retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score"):
        print(f"{key:>20}: {metrics[key]}")
    print(f"\nReport: {paths.baseline_report.relative_to(paths.project_dir)}")
