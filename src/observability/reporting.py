from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.utils import write_text


_SOURCE_FIELDS = ("source_api", "mode", "query", "raw_records", "clean_rows", "run_date")
_CORE_METRICS = ("retrieval_hit_rate", "mean_token_f1", "judge_accuracy", "mean_judge_score")
_FRESHNESS_FIELDS = ("stale_ratio", "is_fresh", "stale_rows", "total_rows", "threshold_days", "max_stale_ratio")

_CAUGHT_BY = {
    ("expect_column_values_to_be_unique", "paper_id"): "trùng paper_id",
    ("expect_column_value_lengths_to_be_between", "summary"): "summary ngắn hơn 30 ký tự",
    ("expect_column_values_to_not_be_null", "paper_id"): "paper_id null",
    ("expect_column_values_to_not_be_null", "title"): "title null",
    ("expect_column_values_to_not_be_null", "text_for_embedding"): "text_for_embedding null",
    ("expect_table_row_count_to_be_between", None): "số dòng ngoài khoảng 5–5000",
}


def generate_phase1_report(
    report_path,
    source_summary: dict[str, Any],
    metrics: dict[str, Any],
    quality: dict[str, Any],
    freshness: dict[str, Any],
) -> None:
    """Write the baseline markdown report from the supplied artifacts."""
    sections = [
        "# Phase 1 Report",
        "",
        _source_section(source_summary),
        "",
        _metrics_section("Metrics", metrics),
        "",
        _quality_section(quality),
        "",
        _freshness_section("Freshness", freshness),
        "",
    ]
    write_text(Path(report_path), "\n".join(sections))


def generate_corruption_report(
    report_path,
    baseline_metrics: dict[str, Any],
    corrupted_metrics: dict[str, Any],
    repaired_metrics: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> None:
    """Write the three-way comparison report from the supplied artifacts."""
    metric_names = _comparison_metric_names(baseline_metrics, corrupted_metrics, repaired_metrics)
    sections = [
        "# Corruption Comparison Report",
        "",
        _comparison_table(metric_names, baseline_metrics, corrupted_metrics, repaired_metrics),
        "",
        _expectation_comparison(corrupted_quality, repaired_quality),
        "",
        _freshness_comparison(corrupted_freshness, repaired_freshness),
        "",
        _analysis_section(
            metric_names,
            baseline_metrics,
            corrupted_metrics,
            repaired_metrics,
            corrupted_quality,
            repaired_quality,
            corrupted_freshness,
            repaired_freshness,
        ),
        "",
    ]
    breakdown = _question_type_section(baseline_metrics, corrupted_metrics, repaired_metrics)
    if breakdown:
        sections.extend([breakdown, ""])
    write_text(Path(report_path), "\n".join(sections))


def summarize_by_question_type(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate hit rate and token F1 for each question_type."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in answers:
        grouped.setdefault(str(item.get("question_type") or "unknown"), []).append(item)
    rows: list[dict[str, Any]] = []
    for question_type, items in grouped.items():
        hits = [1.0 if item.get("retrieval_hit") else 0.0 for item in items]
        scores = [_as_float(item.get("token_f1")) for item in items]
        token_scores = [score for score in scores if score is not None]
        rows.append(
            {
                "question_type": question_type,
                "samples": len(items),
                "retrieval_hit_rate": sum(hits) / len(hits) if hits else None,
                "mean_token_f1": sum(token_scores) / len(token_scores) if token_scores else None,
            }
        )
    return rows


def _source_section(source_summary: dict[str, Any]) -> str:
    source = source_summary or {}
    fields = list(_SOURCE_FIELDS)
    fields.extend(key for key in source if key not in fields)
    rows = [_table_row("Field", "Value"), _table_rule(2)]
    for field in fields:
        rows.append(_table_row(field, _cell(source.get(field))))
    return "\n".join(["## Source", "", *rows])


def _metrics_section(title: str, metrics: dict[str, Any]) -> str:
    payload = metrics or {}
    rows = [_table_row("Metric", "Value"), _table_rule(2)]
    for name in _metric_names(payload):
        rows.append(_table_row(name, _cell(payload.get(name))))
    if "ragas" in payload:
        rows.append(_table_row("ragas", _cell(payload.get("ragas"))))
    return "\n".join([f"## {title}", "", *rows])


def _quality_section(quality: dict[str, Any]) -> str:
    payload = quality or {}
    lines = [
        "## Data quality",
        "",
        f"GX success: {_cell(payload.get('success'))}",
        "",
        _expectation_table(payload.get("expectations") or []),
    ]
    return "\n".join(lines)


def _freshness_section(title: str, freshness: dict[str, Any]) -> str:
    payload = freshness or {}
    fields = [field for field in _FRESHNESS_FIELDS if field in payload or field in {"stale_ratio", "is_fresh"}]
    fields.extend(key for key in payload if key not in fields)
    rows = [_table_row("Field", "Value"), _table_rule(2)]
    for field in fields:
        rows.append(_table_row(field, _cell(payload.get(field))))
    return "\n".join([f"## {title}", "", *rows])


def _comparison_table(
    metric_names: list[str],
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
    repaired: dict[str, Any],
) -> str:
    rows = [
        _table_row("Metric", "Baseline", "Corrupted", "Repaired", "Δ (corrupted − baseline)"),
        _table_rule(5),
    ]
    for name in metric_names:
        base = _lookup_metric(baseline, name)
        corrupt = _lookup_metric(corrupted, name)
        repair = _lookup_metric(repaired, name)
        rows.append(
            _table_row(
                name,
                _cell(base),
                _cell(corrupt),
                _cell(repair),
                _cell(_delta(corrupt, base)),
            )
        )
    return "\n".join(["## Metrics", "", *rows])


def _expectation_comparison(corrupted_quality: dict[str, Any], repaired_quality: dict[str, Any]) -> str:
    corrupted = _index_expectations((corrupted_quality or {}).get("expectations") or [])
    repaired = _index_expectations((repaired_quality or {}).get("expectations") or [])
    keys = list(dict.fromkeys([*corrupted, *repaired]))
    rows = [
        _table_row("Expectation", "Column", "Corrupted", "Repaired"),
        _table_rule(4),
    ]
    for key in keys:
        name, column = key
        rows.append(
            _table_row(
                name,
                column or "—",
                _pass_fail(corrupted.get(key)),
                _pass_fail(repaired.get(key)),
            )
        )
    lines = [
        "## Great Expectations",
        "",
        f"Corrupted GX success: {_cell((corrupted_quality or {}).get('success'))}",
        "",
        f"Repaired GX success: {_cell((repaired_quality or {}).get('success'))}",
        "",
        *rows,
    ]
    return "\n".join(lines)


def _freshness_comparison(corrupted: dict[str, Any], repaired: dict[str, Any]) -> str:
    left = corrupted or {}
    right = repaired or {}
    fields = [field for field in _FRESHNESS_FIELDS if field in left or field in right or field in {"stale_ratio", "is_fresh"}]
    rows = [_table_row("Signal", "Corrupted", "Repaired"), _table_rule(3)]
    for field in fields:
        rows.append(_table_row(field, _cell(left.get(field)), _cell(right.get(field))))
    return "\n".join(["## Freshness", "", *rows])


def _analysis_section(
    metric_names: list[str],
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
    repaired: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
    corrupted_freshness: dict[str, Any],
    repaired_freshness: dict[str, Any],
) -> str:
    drops = _metric_deltas(metric_names, baseline, corrupted)
    parts = [
        "## Analysis",
        "",
        "### Metric sụt mạnh nhất",
        "",
        _drop_paragraph(drops),
        "",
        "### Expectation bắt được lỗi nào",
        "",
        _caught_paragraph(corrupted_quality, repaired_quality),
        "",
        "### Silent failure",
        "",
        _silent_failure_paragraph(drops, corrupted_quality),
        "",
        "### Repair phục hồi gì",
        "",
        _repair_paragraph(metric_names, baseline, corrupted, repaired, corrupted_quality, repaired_quality),
        "",
        "### Freshness",
        "",
        _freshness_paragraph(corrupted_freshness, repaired_freshness),
    ]
    return "\n".join(parts)


def _question_type_section(*metric_sets: dict[str, Any]) -> str:
    labels = ("Baseline", "Corrupted", "Repaired")
    blocks: list[str] = []
    for label, metrics in zip(labels, metric_sets, strict=True):
        answers = (metrics or {}).get("answers")
        if not isinstance(answers, list) or not answers:
            continue
        rows = [_table_row("question_type", "samples", "retrieval_hit_rate", "mean_token_f1"), _table_rule(4)]
        for item in summarize_by_question_type(answers):
            rows.append(
                _table_row(
                    item["question_type"],
                    _cell(item["samples"]),
                    _cell(item["retrieval_hit_rate"]),
                    _cell(item["mean_token_f1"]),
                )
            )
        blocks.extend([f"### {label}", "", *rows, ""])
    if not blocks:
        return ""
    return "\n".join(["## Breakdown theo question_type", "", *blocks]).rstrip()


def _drop_paragraph(drops: list[tuple[str, float, float, float]]) -> str:
    negative = [item for item in drops if item[1] < 0]
    if not drops:
        return "Không có metric số để so sánh baseline với corrupted."
    if not negative:
        names = ", ".join(item[0] for item in drops)
        return f"Không có metric nào giảm. Các metric đã so sánh: {names}."
    worst = min(negative, key=lambda item: item[1])
    name, delta, base, corrupt = worst
    tied = [item[0] for item in negative if item[1] == delta]
    label = ", ".join(tied) if len(tied) > 1 else name
    return (
        f"Metric sụt mạnh nhất: {label}. "
        f"{name} giảm từ {_cell(base)} xuống {_cell(corrupt)} "
        f"(Δ = {_cell(delta)})."
    )


def _caught_paragraph(corrupted_quality: dict[str, Any], repaired_quality: dict[str, Any]) -> str:
    corrupted = _index_expectations((corrupted_quality or {}).get("expectations") or [])
    repaired = _index_expectations((repaired_quality or {}).get("expectations") or [])
    if not corrupted and not repaired:
        return "Không có kết quả expectation để đối chiếu."
    lines: list[str] = []
    for key, item in corrupted.items():
        name, column = key
        observed = _observed_phrase(item.get("observed"))
        target = _CAUGHT_BY.get(key, "vi phạm trên cột này" if column else "vi phạm mức bảng")
        if item.get("success") is False:
            repair_state = _pass_fail(repaired.get(key))
            lines.append(
                f"- `{name}`"
                + (f" ({column})" if column else "")
                + f" fail trên corrupted, observed {observed}: bắt được {target}. "
                + f"Sau repair: {repair_state}."
            )
        else:
            lines.append(
                f"- `{name}`"
                + (f" ({column})" if column else "")
                + " pass trên corrupted, nên không bắt được lỗi ở điều kiện này."
            )
    return "\n".join(lines)


def _silent_failure_paragraph(drops: list[tuple[str, float, float, float]], quality: dict[str, Any]) -> str:
    expectations = _index_expectations((quality or {}).get("expectations") or [])
    negative = [item for item in drops if item[1] < 0]
    if not negative:
        return "Không có metric giảm, nên không có silent failure trên các chỉ số đã đo."
    failed = [key for key, item in expectations.items() if item.get("success") is False]
    passed = [key for key, item in expectations.items() if item.get("success") is True]
    drop_text = ", ".join(f"{name} (Δ = {_cell(delta)})" for name, delta, _, _ in negative)
    if not expectations:
        return (
            f"{drop_text} giảm nhưng không có expectation GX trong payload, "
            "nên chưa kết luận gate có bắt được lỗi hay không."
        )
    if not failed:
        return (
            f"Silent failure: {drop_text} giảm trong khi mọi expectation GX vẫn pass "
            f"(GX success = {_cell((quality or {}).get('success'))}). "
            "Gate không nhìn thấy suy giảm này."
        )
    caught = ", ".join(f"`{name}`" + (f" ({column})" if column else "") for name, column in failed)
    silent_checks = ", ".join(f"`{name}`" + (f" ({column})" if column else "") for name, column in passed)
    message = f"GX bắt được lỗi qua {caught}. Metric giảm: {drop_text}."
    if silent_checks:
        message += f" Các expectation vẫn pass ({silent_checks}) không phát hiện phần suy giảm đó."
    return message


def _repair_paragraph(
    metric_names: list[str],
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
    repaired: dict[str, Any],
    corrupted_quality: dict[str, Any],
    repaired_quality: dict[str, Any],
) -> str:
    lines: list[str] = []
    for name in metric_names:
        base = _as_float(_lookup_metric(baseline, name))
        corrupt = _as_float(_lookup_metric(corrupted, name))
        repair = _as_float(_lookup_metric(repaired, name))
        if base is None or corrupt is None or repair is None:
            continue
        before = abs(corrupt - base)
        after = abs(repair - base)
        if after < before:
            movement = "phục hồi một phần" if after > 0 else "phục hồi về baseline"
        elif after == before:
            movement = "không đổi khoảng cách tới baseline"
        else:
            movement = "xa baseline hơn sau repair"
        lines.append(
            f"- `{name}`: corrupted {_cell(corrupt)} → repaired {_cell(repair)} "
            f"(baseline {_cell(base)}); {movement}."
        )
    corrupted = _index_expectations((corrupted_quality or {}).get("expectations") or [])
    repaired_items = _index_expectations((repaired_quality or {}).get("expectations") or [])
    for key, item in corrupted.items():
        if item.get("success") is False and (repaired_items.get(key) or {}).get("success") is True:
            name, column = key
            lines.append(
                f"- Expectation `{name}`"
                + (f" ({column})" if column else "")
                + " fail trên corrupted và pass sau repair."
            )
    if not lines:
        return "Không đủ số liệu để kết luận repair phục hồi metric hay expectation nào."
    return "\n".join(lines)


def _freshness_paragraph(corrupted: dict[str, Any], repaired: dict[str, Any]) -> str:
    left = corrupted or {}
    right = repaired or {}
    left_ratio = _as_float(left.get("stale_ratio"))
    right_ratio = _as_float(right.get("stale_ratio"))
    if left_ratio is None and right_ratio is None:
        return "Không có stale_ratio để so sánh freshness."
    text = (
        f"Corrupted stale_ratio = {_cell(left.get('stale_ratio'))}, is_fresh = {_cell(left.get('is_fresh'))}. "
        f"Repaired stale_ratio = {_cell(right.get('stale_ratio'))}, is_fresh = {_cell(right.get('is_fresh'))}."
    )
    if left_ratio is not None and right_ratio is not None and right_ratio < left_ratio:
        text += " Repair làm giảm tỷ lệ bài quá hạn."
    elif left_ratio is not None and right_ratio is not None and right_ratio > left_ratio:
        text += " Repair không làm corpus tươi hơn."
    return text


def _metric_deltas(
    metric_names: list[str],
    baseline: dict[str, Any],
    corrupted: dict[str, Any],
) -> list[tuple[str, float, float, float]]:
    drops: list[tuple[str, float, float, float]] = []
    for name in metric_names:
        base = _as_float(_lookup_metric(baseline, name))
        corrupt = _as_float(_lookup_metric(corrupted, name))
        if base is None or corrupt is None:
            continue
        drops.append((name, corrupt - base, base, corrupt))
    return drops


def _comparison_metric_names(*metric_sets: dict[str, Any]) -> list[str]:
    names = list(_CORE_METRICS)
    seen = set(names)
    for metrics in metric_sets:
        for name in _metric_names(metrics or {}):
            if name not in seen:
                names.append(name)
                seen.add(name)
        ragas = (metrics or {}).get("ragas")
        if isinstance(ragas, dict):
            for key in ragas:
                label = f"ragas.{key}"
                if label not in seen:
                    names.append(label)
                    seen.add(label)
        elif "ragas" in (metrics or {}) and "ragas" not in seen:
            names.append("ragas")
            seen.add("ragas")
    return names


def _metric_names(metrics: dict[str, Any]) -> list[str]:
    names = list(_CORE_METRICS)
    for key, value in (metrics or {}).items():
        if key in names or key in {"ragas", "answers"}:
            continue
        if _as_float(value) is not None or isinstance(value, str):
            names.append(key)
    return names


def _lookup_metric(metrics: dict[str, Any], name: str) -> Any:
    payload = metrics or {}
    if name.startswith("ragas.") and isinstance(payload.get("ragas"), dict):
        return payload["ragas"].get(name.split(".", 1)[1])
    return payload.get(name)


def _index_expectations(expectations: list[dict[str, Any]]) -> dict[tuple[str, str | None], dict[str, Any]]:
    indexed: dict[tuple[str, str | None], dict[str, Any]] = {}
    for item in expectations:
        if not isinstance(item, dict):
            continue
        name = str(item.get("expectation") or item.get("type") or "unknown")
        column = item.get("column")
        if column is None:
            kwargs = item.get("kwargs") or {}
            column = kwargs.get("column") if isinstance(kwargs, dict) else None
        indexed[(name, str(column) if column else None)] = item
    return indexed


def _expectation_table(expectations: list[dict[str, Any]]) -> str:
    rows = [_table_row("Expectation", "Column", "Result", "Observed"), _table_rule(4)]
    for key, item in _index_expectations(expectations).items():
        name, column = key
        rows.append(_table_row(name, column or "—", _pass_fail(item), _observed_phrase(item.get("observed"))))
    return "\n".join(rows)


def _observed_phrase(observed: Any) -> str:
    if not isinstance(observed, dict) or not observed:
        return _cell(observed)
    if "observed_value" in observed:
        return _cell(observed["observed_value"])
    if "unexpected_count" in observed:
        return _cell(observed["unexpected_count"])
    return _cell(observed)


def _pass_fail(item: dict[str, Any] | None) -> str:
    if not item or "success" not in item:
        return "—"
    return "pass" if item.get("success") else "fail"


def _delta(corrupted: Any, baseline: Any) -> float | None:
    corrupt = _as_float(corrupted)
    base = _as_float(baseline)
    if corrupt is None or base is None:
        return None
    return corrupt - base


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _cell(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, str):
        return value.replace("|", "\\|").replace("\n", " ")
    try:
        rendered = json.dumps(value, ensure_ascii=False)
    except TypeError:
        rendered = str(value)
    return rendered.replace("|", "\\|").replace("\n", " ")


def _table_row(*cells: Any) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def _table_rule(columns: int) -> str:
    return "| " + " | ".join("---" for _ in range(columns)) + " |"
