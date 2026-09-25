from __future__ import annotations

import json
from typing import Any

import great_expectations as gx
import great_expectations.expectations as gxe
import pandas as pd

from core.config import Settings
from core.utils import now_utc, write_json

MIN_ROWS = 5
MAX_ROWS = 5000
MIN_SUMMARY_CHARS = 30
MIN_TITLE_CHARS = 8
MAX_STALE_RATIO = 0.25
# Three or more consecutive characters that never appear in a normal abstract (e.g. "#@$~^").
NOISE_PATTERN = r"[^A-Za-z0-9\s.,;:()'\"/%?!&+\-]{3,}"


def _build_expectations() -> list[tuple[str, Any]]:
    """Return (tier, expectation) pairs: the 4 required gates plus extra corruption detectors."""
    return [
        ("required", gxe.ExpectTableRowCountToBeBetween(min_value=MIN_ROWS, max_value=MAX_ROWS)),
        ("required", gxe.ExpectColumnValuesToNotBeNull(column="paper_id")),
        ("required", gxe.ExpectColumnValuesToNotBeNull(column="title")),
        ("required", gxe.ExpectColumnValuesToNotBeNull(column="text_for_embedding")),
        ("required", gxe.ExpectColumnValuesToBeUnique(column="paper_id")),
        ("required", gxe.ExpectColumnValueLengthsToBeBetween(column="summary", min_value=MIN_SUMMARY_CHARS)),
        ("extra", gxe.ExpectColumnValueLengthsToBeBetween(column="title", min_value=MIN_TITLE_CHARS)),
        ("extra", gxe.ExpectColumnValuesToNotMatchRegex(column="summary", regex=NOISE_PATTERN)),
        ("extra", gxe.ExpectColumnValuesToNotBeNull(column="age_days")),
    ]


def _to_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _gx_frame(df: pd.DataFrame) -> pd.DataFrame:
    # List columns are not hashable, which breaks GX's pandas metrics; the checks only need scalars.
    frame = df.drop(columns=[column for column in ("authors", "categories") if column in df.columns])
    for column in frame.columns:
        if pd.api.types.is_string_dtype(frame[column]):
            frame[column] = frame[column].astype(object)
    return frame


def _freshness_summary(df: pd.DataFrame, settings: Settings) -> dict[str, Any]:
    total_rows = int(len(df))
    ages = pd.to_numeric(df["age_days"], errors="coerce") if "age_days" in df else pd.Series(dtype=float)
    stale_rows = int((ages > settings.freshness_threshold_days).sum())
    stale_ratio = stale_rows / total_rows if total_rows else 1.0
    published = pd.to_datetime(df["published"], errors="coerce") if "published" in df else pd.Series(dtype="datetime64[ns]")
    return {
        "latest_published": published.max().date().isoformat() if published.notna().any() else None,
        "oldest_published": published.min().date().isoformat() if published.notna().any() else None,
        "stale_rows": stale_rows,
        "total_rows": total_rows,
        "stale_ratio": round(stale_ratio, 4),
        "freshness_threshold_days": settings.freshness_threshold_days,
        "max_stale_ratio": MAX_STALE_RATIO,
        "median_age_days": float(ages.median()) if ages.notna().any() else None,
        "is_fresh": total_rows > 0 and stale_ratio <= MAX_STALE_RATIO,
    }


def run_data_quality_checks(df: pd.DataFrame, settings: Settings, report_name: str) -> dict[str, Any]:
    """Validate a clean dataframe with an ephemeral Great Expectations 1.x context.

    `success` reflects the GX expectation suite only; the freshness SLA is reported alongside
    and combined into `gate_passed`, so a stale-but-valid corpus raises an alert without
    being mistaken for a schema/content failure.
    """
    context = gx.get_context(mode="ephemeral")
    data_source = context.data_sources.add_pandas(name="papers_source")
    data_asset = data_source.add_dataframe_asset(name="papers_asset")
    batch_def = data_asset.add_batch_definition_whole_dataframe("papers_batch")
    batch = batch_def.get_batch(batch_parameters={"dataframe": _gx_frame(df)})

    tiers = _build_expectations()
    suite = context.suites.add(gx.ExpectationSuite(name=f"papers_{report_name}_suite"))
    tier_by_id = {}
    for tier, expectation in tiers:
        tier_by_id[suite.add_expectation(expectation).id] = tier
    validation = batch.validate(suite)

    checks = []
    for result in validation.results:
        config = result.expectation_config
        tier = tier_by_id.get(config.id, "extra")
        details = result.result or {}
        checks.append(
            {
                "expectation": config.type,
                "tier": tier,
                "column": config.kwargs.get("column"),
                "kwargs": {
                    key: value
                    for key, value in config.kwargs.items()
                    if key not in {"column", "batch_id"} and value is not None
                },
                "success": bool(result.success),
                "observed_value": details.get("observed_value"),
                "unexpected_count": details.get("unexpected_count"),
                "unexpected_percent": details.get("unexpected_percent"),
                "partial_unexpected_list": (details.get("partial_unexpected_list") or [])[:5],
            }
        )

    freshness = _freshness_summary(df, settings)
    payload = {
        "report_name": report_name,
        "generated_at": now_utc().isoformat(),
        "engine": f"great_expectations {gx.__version__} (ephemeral context)",
        "row_count": int(len(df)),
        "success": bool(validation.success),
        "evaluated_expectations": len(checks),
        "successful_expectations": sum(check["success"] for check in checks),
        "failed_expectations": [check["expectation"] + (f"({check['column']})" if check["column"] else "") for check in checks if not check["success"]],
        "checks": checks,
        "freshness": freshness,
        "gate_passed": bool(validation.success) and freshness["is_fresh"],
    }
    payload = _to_jsonable(payload)
    write_json(settings.paths.quality_dir / f"{report_name}_quality_report.json", payload)
    return payload


def build_freshness_report(df: pd.DataFrame, settings: Settings, report_path) -> dict[str, Any]:
    """Summarise corpus freshness: alert (`is_fresh=False`) when >25% of papers are older than 180 days."""
    payload = {"generated_at": now_utc().isoformat(), **_freshness_summary(df, settings)}
    payload = _to_jsonable(payload)
    write_json(report_path, payload)
    return payload
