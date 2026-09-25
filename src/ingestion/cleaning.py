from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
import html
import re

import pandas as pd

from core.utils import compact_join, normalize_whitespace
from ingestion.crossref import PaperRecord

CLEAN_COLUMNS = [
    "paper_id",
    "title",
    "summary",
    "authors",
    "categories",
    "primary_category",
    "published",
    "updated",
    "age_days",
    "abs_url",
    "pdf_url",
    "comment",
    "authors_joined",
    "categories_joined",
    "summary_chars",
    "text_for_embedding",
]


def clean_text(value) -> str:
    """Remove leftover markup/HTML entities and collapse whitespace."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    return normalize_whitespace(html.unescape(text))


def _clean_list(values) -> list[str]:
    if isinstance(values, str):
        values = [values]
    cleaned: list[str] = []
    for value in values or []:
        item = clean_text(value)
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _parse_date(value) -> date | None:
    parsed = pd.to_datetime(clean_text(value), errors="coerce", utc=True)
    return None if pd.isna(parsed) else parsed.date()


def build_text_for_embedding(row: dict) -> str:
    return "\n".join(
        [
            f"Title: {row['title']}",
            f"Authors: {row['authors_joined']}",
            f"Published: {row['published']}",
            f"Categories: {row['categories_joined']}",
            f"Summary: {row['summary']}",
        ]
    )


def add_derived_columns(df: pd.DataFrame) -> pd.DataFrame:
    """(Re)build the helper columns that depend on title/summary/authors/categories/published."""
    df = df.copy()
    df["authors_joined"] = df["authors"].apply(compact_join)
    df["categories_joined"] = df["categories"].apply(compact_join)
    df["summary_chars"] = df["summary"].str.len().astype(int)
    df["text_for_embedding"] = [build_text_for_embedding(row) for row in df.to_dict(orient="records")]
    return df


def build_clean_dataframe(records: list[PaperRecord], run_date: datetime) -> pd.DataFrame:
    """Turn raw `PaperRecord`s into a deduplicated, embed-ready dataframe.

    Pure function of (records, run_date): re-running it on the same raw snapshot always
    yields the same dataframe, which is what makes the repair step idempotent.
    """
    today = run_date.date() if isinstance(run_date, datetime) else run_date
    rows = []
    for record in records:
        raw = asdict(record)
        published = _parse_date(raw["published"])
        updated = _parse_date(raw["updated"]) or published
        categories = _clean_list(raw["categories"])
        rows.append(
            {
                "paper_id": clean_text(raw["paper_id"]),
                "title": clean_text(raw["title"]),
                "summary": clean_text(raw["summary"]),
                "authors": _clean_list(raw["authors"]),
                "categories": categories,
                "primary_category": clean_text(raw["primary_category"]) or (categories[0] if categories else "Uncategorized"),
                "published": published.isoformat() if published else "",
                "updated": updated.isoformat() if updated else "",
                "age_days": (today - published).days if published else None,
                "abs_url": clean_text(raw["abs_url"]),
                "pdf_url": clean_text(raw["pdf_url"]) or clean_text(raw["abs_url"]),
                "comment": clean_text(raw["comment"]),
            }
        )

    df = pd.DataFrame(rows, columns=CLEAN_COLUMNS[:12])
    if df.empty:
        return pd.DataFrame(columns=CLEAN_COLUMNS)

    # Drop rows that cannot be served: no id, no title, no summary or unparseable publish date.
    usable = (df["paper_id"] != "") & (df["title"] != "") & (df["summary"] != "") & (df["published"] != "")
    df = df[usable]
    if df.empty:
        return pd.DataFrame(columns=CLEAN_COLUMNS)

    # DOIs are case-insensitive: keep the most recently updated version of each paper.
    df = (
        df.assign(_doi_key=df["paper_id"].str.lower())
        .sort_values(["_doi_key", "updated"], ascending=[True, False])
        .drop_duplicates(subset="_doi_key", keep="first")
        .drop(columns="_doi_key")
    )

    df = add_derived_columns(df)
    df["age_days"] = df["age_days"].astype(int)
    df = df.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    return df[CLEAN_COLUMNS]
