from __future__ import annotations

from typing import Any

from core.utils import now_utc, write_text

METRIC_LABELS = [
    ("retrieval_hit_rate", "Retrieval Hit Rate"),
    ("mean_token_f1", "Mean Token F1"),
    ("judge_accuracy", "LLM Judge Accuracy"),
    ("mean_judge_score", "Mean Judge Score (1-5)"),
]
QUESTION_TYPES = ["summary", "authors", "date", "categories"]


def _fmt(value: Any, digits: int = 4) -> str:
    if isinstance(value, bool):
        return "✅ True" if value else "❌ False"
    if isinstance(value, (int, float)):
        return f"{value:.{digits}f}" if isinstance(value, float) else str(value)
    return "—" if value is None else str(value)


def _delta(new: Any, old: Any) -> str:
    if not isinstance(new, (int, float)) or not isinstance(old, (int, float)):
        return "—"
    diff = new - old
    return f"{diff:+.4f}"


def _quality_table(states: list[tuple[str, dict[str, Any]]]) -> list[str]:
    """One row per expectation, one column per state."""
    header = "| Expectation | Tier | " + " | ".join(name for name, _ in states) + " |"
    lines = [header, "|---|---|" + "---|" * len(states)]
    keys: list[tuple[str, str | None, str]] = []
    for _, quality in states:
        for check in quality.get("checks", []):
            key = (check["expectation"], check.get("column"), check.get("tier", ""))
            if key not in keys:
                keys.append(key)
    for expectation, column, tier in keys:
        cells = []
        for _, quality in states:
            match = next(
                (c for c in quality.get("checks", []) if c["expectation"] == expectation and c.get("column") == column),
                None,
            )
            if match is None:
                cells.append("—")
                continue
            status = "PASS" if match["success"] else "FAIL"
            if match.get("unexpected_count"):
                status += f" ({match['unexpected_count']} bad)"
            elif match.get("observed_value") is not None and not column:
                status += f" (observed={match['observed_value']})"
            cells.append(status)
        label = f"`{expectation}`" + (f" on `{column}`" if column else "")
        lines.append(f"| {label} | {tier} | " + " | ".join(cells) + " |")
    return lines


def _judge_sources(answers: list[dict[str, Any]]) -> str:
    """How many verdicts came from the real LLM judge vs the token-F1 fallback in evaluation.metrics."""
    fallback = sum(1 for item in answers if item.get("judge", {}).get("reasoning", "").startswith("Fallback heuristic"))
    return f"{len(answers) - fallback} LLM / {fallback} fallback"


def _per_type_scores(answers: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    scores: dict[str, dict[str, float]] = {}
    for question_type in QUESTION_TYPES:
        subset = [item for item in answers if item.get("question_type") == question_type]
        if not subset:
            continue
        scores[question_type] = {
            "n": len(subset),
            "hit_rate": sum(1.0 for item in subset if item["retrieval_hit"]) / len(subset),
            "token_f1": sum(item["token_f1"] for item in subset) / len(subset),
        }
    return scores


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
    answers: list[dict[str, Any]] | None = None,
) -> None:
    """Write the baseline (Phase 1) markdown report."""
    lines = [
        "# Phase 1 Report — Baseline Data Pipeline",
        "",
        f"_Generated automatically by `script/run_phase1.py` at {now_utc().isoformat(timespec='seconds')}._",
        "",
        "## 1. Source & Lineage",
        "",
        "| Item | Value |",
        "|---|---|",
    ]
    lines += [f"| {key} | {_fmt(value)} |" for key, value in source_summary.items()]

    lines += [
        "",
        "## 2. Data Quality Gate (Great Expectations 1.x)",
        "",
        f"- Engine: {quality.get('engine', 'great_expectations')}",
        f"- Suite success: **{_fmt(quality.get('success'))}** "
        f"({quality.get('successful_expectations')}/{quality.get('evaluated_expectations')} expectations passed)",
        f"- Gate passed (GX + freshness): **{_fmt(quality.get('gate_passed'))}**",
        "",
    ]
    lines += _quality_table([("Baseline", quality)])

    lines += [
        "",
        "## 3. Freshness SLA",
        "",
        f"Rule: alert when more than {freshness.get('max_stale_ratio', 0.25):.0%} of papers are older than "
        f"{freshness.get('freshness_threshold_days')} days.",
        "",
        "| Metric | Value |",
        "|---|---|",
    ]
    for key in ("latest_published", "oldest_published", "stale_rows", "total_rows", "stale_ratio", "median_age_days", "is_fresh"):
        lines.append(f"| {key} | {_fmt(freshness.get(key))} |")

    lines += [
        "",
        "## 4. Baseline RAG Evaluation",
        "",
        f"Samples: {metrics.get('samples')}",
        "",
        "| Metric | Baseline |",
        "|---|---|",
    ]
    lines += [f"| {label} | {_fmt(metrics.get(key))} |" for key, label in METRIC_LABELS]
    if answers:
        lines.append(f"| Judge verdict source | {_judge_sources(answers)} |")
        per_type = _per_type_scores(answers)
        lines += ["", "| Question type | n | Hit Rate | Token F1 |", "|---|---|---|---|"]
        lines += [
            f"| {question_type} | {score['n']} | {score['hit_rate']:.2f} | {score['token_f1']:.2f} |"
            for question_type, score in per_type.items()
        ]
    ragas = metrics.get("ragas")
    if ragas:
        lines += ["", f"Ragas: `{ragas}`"]

    lines += [
        "",
        "## 5. Notes",
        "",
        "- The quality gate runs **before** indexing: a failing GX suite stops Phase 1 so bad data never reaches ChromaDB.",
        "- A freshness breach does not block indexing; it is surfaced as an alert (`is_fresh = False`).",
        "- All numbers above are read from the artifacts produced in this run "
        "(`data/results/baseline_metrics.json`, `data/quality/*.json`).",
        "",
    ]
    write_text(report_path, "\n".join(lines))


def _analysis(
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
    repaired: dict[str, Any],
    corrupted_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_quality: dict[str, Any],
    repaired_freshness: dict[str, Any],
    corrupted_answers: list[dict[str, Any]] | None = None,
) -> list[str]:
    lines = []
    hit_drop = baseline.get("retrieval_hit_rate", 0) - corrupted.get("retrieval_hit_rate", 0)
    f1_drop = baseline.get("mean_token_f1", 0) - corrupted.get("mean_token_f1", 0)
    lines.append(
        f"- **Silent failure:** on corrupted data the pipeline still returned an answer for every question "
        f"(no exception), yet Hit Rate fell by {hit_drop:.2f} and Token F1 by {f1_drop:.2f} versus the baseline."
    )
    wrong_doc = [item for item in corrupted_answers or [] if not item["retrieval_hit"]]
    if wrong_doc:
        examples = "; ".join(
            f"{item['id']}: answered \"{item['answer'][:50]}\" (expected \"{item['ground_truth'][:50]}\")"
            for item in wrong_doc[:3]
        )
        lines.append(
            f"- **Confident wrong source:** {len(wrong_doc)} question(s) were answered from a different paper than "
            f"the ground truth, without any warning — {examples}."
        )
    failed = corrupted_quality.get("failed_expectations") or []
    lines.append(
        f"- **Detection:** the GX gate flagged the corrupted batch with {len(failed)} failing expectation(s): "
        + (", ".join(f"`{name}`" for name in failed) if failed else "none")
        + "."
    )
    lines.append(
        f"- **Freshness:** stale ratio went from {repaired_freshness.get('stale_ratio')} (repaired) to "
        f"{corrupted_freshness.get('stale_ratio')} (corrupted); `is_fresh` = {corrupted_freshness.get('is_fresh')} "
        "on the corrupted data. Stale dates are invisible to schema checks, which is why a separate freshness SLA is needed."
    )
    recovered = all(
        abs(repaired.get(key, 0) - baseline.get(key, 0)) < 1e-9 for key in ("retrieval_hit_rate", "mean_token_f1")
    )
    lines.append(
        f"- **Repair:** rebuilding from the raw snapshot gives GX success = {repaired_quality.get('success')} and "
        + (
            "retrieval/F1 metrics identical to the baseline."
            if recovered
            else "retrieval/F1 metrics that differ from the baseline — investigate before serving."
        )
    )
    return lines


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
    corruption_log: dict[str, Any] | None = None,
    repair_summary: dict[str, Any] | None = None,
    answers_by_state: dict[str, list[dict[str, Any]]] | None = None,
    baseline_quality: dict[str, Any] | None = None,
) -> None:
    """Write the Baseline vs Corrupted vs Repaired comparison report."""
    lines = [
        "# Corruption & Repair Report — Baseline vs Corrupted vs Repaired",
        "",
        f"_Generated automatically by `script/run_corruption_flow.py` at {now_utc().isoformat(timespec='seconds')}._",
        "",
        "## 1. RAG Metrics — 3-State Comparison",
        "",
        "| Metric | Baseline | Corrupted | Repaired | Δ Corrupted vs Baseline | Δ Repaired vs Baseline |",
        "|---|---|---|---|---|---|",
    ]
    for key, label in METRIC_LABELS:
        base, corr, rep = baseline_metrics.get(key), corrupted_metrics.get(key), repaired_metrics.get(key)
        lines.append(
            f"| {label} | {_fmt(base)} | {_fmt(corr)} | {_fmt(rep)} | {_delta(corr, base)} | {_delta(rep, base)} |"
        )
    if answers_by_state:
        sources = [_judge_sources(answers_by_state.get(state) or []) for state in ("baseline", "corrupted", "repaired")]
        lines.append("| Judge verdict source | " + " | ".join(sources) + " | — | — |")
        lines += [
            "",
            "> Judge verdicts marked *fallback* come from the token-F1 heuristic in `evaluation/metrics.py`, "
            "used when the LLM judge call fails (e.g. provider rate limits). Hit Rate and Token F1 are deterministic.",
        ]

    if answers_by_state:
        per_state = {state: _per_type_scores(answers) for state, answers in answers_by_state.items()}
        states = list(per_state)
        lines += [
            "",
            "### Breakdown by question type (Hit Rate / Token F1)",
            "",
            "| Question type | n | " + " | ".join(state.capitalize() for state in states) + " |",
            "|---|---|" + "---|" * len(states),
        ]
        for question_type in QUESTION_TYPES:
            first = next((per_state[s][question_type] for s in states if question_type in per_state[s]), None)
            if first is None:
                continue
            cells = []
            for state in states:
                score = per_state[state].get(question_type)
                cells.append(f"{score['hit_rate']:.2f} / {score['token_f1']:.2f}" if score else "—")
            lines.append(f"| {question_type} | {first['n']} | " + " | ".join(cells) + " |")

    lines += ["", "## 2. Data Quality Gate (Great Expectations 1.x)", ""]
    quality_states = ([("Baseline", baseline_quality)] if baseline_quality else []) + [
        ("Corrupted", corrupted_quality),
        ("Repaired", repaired_quality),
    ]
    lines += [
        "| Summary | " + " | ".join(name for name, _ in quality_states) + " |",
        "|---|" + "---|" * len(quality_states),
        "| Row count | " + " | ".join(str(q.get("row_count")) for _, q in quality_states) + " |",
        "| GX suite success | " + " | ".join(_fmt(q.get("success")) for _, q in quality_states) + " |",
        "| Expectations passed | "
        + " | ".join(f"{q.get('successful_expectations')}/{q.get('evaluated_expectations')}" for _, q in quality_states)
        + " |",
        "| Gate passed (GX + freshness) | " + " | ".join(_fmt(q.get("gate_passed")) for _, q in quality_states) + " |",
        "",
    ]
    lines += _quality_table(quality_states)

    lines += [
        "",
        "## 3. Freshness SLA",
        "",
        "| Metric | Corrupted | Repaired |",
        "|---|---|---|",
    ]
    for key in ("latest_published", "oldest_published", "stale_rows", "total_rows", "stale_ratio", "median_age_days", "is_fresh"):
        lines.append(f"| {key} | {_fmt(corrupted_freshness.get(key))} | {_fmt(repaired_freshness.get(key))} |")

    if corruption_log:
        lines += [
            "",
            "## 4. Injected Corruptions",
            "",
            f"Seed: `{corruption_log.get('seed')}` · rows before: {corruption_log.get('rows_before')} · "
            f"rows after: {corruption_log.get('rows_after')}",
            "",
            "| # | Corruption | Rows affected | Test-set questions touched | Real-world failure it simulates | Caught by |",
            "|---|---|---|---|---|---|",
        ]
        eval_items = (answers_by_state or {}).get("corrupted") or []
        for number, step in enumerate(corruption_log.get("corruptions", []), start=1):
            touched = [
                f"{item['id']} ({item['question_type']})"
                for item in eval_items
                if set(item["ground_truth_doc_ids"]) & set(step["paper_ids"])
            ]
            lines.append(
                f"| {number} | `{step['type']}` | {step['rows_affected']} | {', '.join(touched) or 'none'} | "
                f"{step['simulates']} | {step['detected_by']} |"
            )
        if eval_items:
            lines += [
                "",
                "Rows are chosen with a fixed seed, independently of the test set, so a corruption that touches "
                "no test question is still caught by the quality gate but does not move the RAG metrics.",
            ]

    if repair_summary:
        lines += [
            "",
            "## 5. Idempotent Repair",
            "",
            "| Check | Result |",
            "|---|---|",
        ]
        lines += [f"| {key} | {_fmt(value)} |" for key, value in repair_summary.items()]

    lines += ["", "## 6. Analysis", ""]
    lines += _analysis(
        baseline_metrics,
        corrupted_metrics,
        repaired_metrics,
        corrupted_quality,
        corrupted_freshness,
        repaired_quality,
        repaired_freshness,
        corrupted_answers=(answers_by_state or {}).get("corrupted"),
    )
    lines.append("")
    write_text(report_path, "\n".join(lines))
