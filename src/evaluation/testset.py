from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from core.utils import first_sentence, write_json

TEST_SET_SIZE = 10
# Five papers keep every (paper, question_type) pair unique when papers are reused.
MIN_DOCUMENTS = 5
QUESTION_PLAN = (
    "summary",
    "authors",
    "date",
    "categories",
    "summary",
    "authors",
    "date",
    "categories",
    "summary",
    "authors",
)

_REQUIRED_TEXT_COLUMNS = ("paper_id", "title", "summary", "authors_joined", "published", "categories_joined")


def _question(question_type: str, title: str) -> str:
    # Keywords must stay in sync with retrieval.qa._extract_answer.
    templates = {
        "summary": "What is the summary of the paper '{title}'?",
        "authors": "Who authored the paper '{title}'?",
        "date": "When was the paper '{title}' published?",
        "categories": "What categories does the paper '{title}' belong to?",
    }
    return templates[question_type].format(title=title)


def _ground_truth(question_type: str, row: dict[str, Any]) -> str:
    if question_type == "summary":
        return first_sentence(row["summary"])
    if question_type == "authors":
        return row["authors_joined"]
    if question_type == "date":
        return row["published"]
    return row["categories_joined"]


def _eligible_papers(df: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in _REQUIRED_TEXT_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"Clean dataframe is missing columns required for the test set: {missing}")
    frame = df.drop_duplicates(subset=["paper_id"], keep="first").copy()
    for column in _REQUIRED_TEXT_COLUMNS:
        frame[column] = frame[column].fillna("").astype(str).str.strip()
    usable = (frame[list(_REQUIRED_TEXT_COLUMNS)] != "").all(axis=1)
    # qa.answer_question extracts the title with r"'([^']+)'", so apostrophes would break the exact lookup.
    usable &= ~frame["title"].str.contains("'", regex=False)
    frame = frame[usable]
    return frame.sort_values(by=["published", "paper_id"], ascending=[False, True], kind="stable").reset_index(drop=True)


def plan_eval_items(df: pd.DataFrame) -> list[tuple[str, dict[str, Any]]]:
    """Deterministically pair each planned question type with a paper row (newest first)."""
    papers = _eligible_papers(df)
    if len(papers) < MIN_DOCUMENTS:
        raise ValueError(
            f"Need at least {MIN_DOCUMENTS} usable documents to build the test set, got {len(papers)} "
            f"(from {len(df)} rows). Check the cleaning step output."
        )
    picked = min(TEST_SET_SIZE, len(papers))
    # Evenly spaced over newest→oldest; position 0 is always the newest paper, so drop_latest hits the set.
    positions = [round(i * (len(papers) - 1) / (picked - 1)) for i in range(picked)]
    rows = [papers.iloc[position].to_dict() for position in positions]
    return [(question_type, rows[i % len(rows)]) for i, question_type in enumerate(QUESTION_PLAN)]


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Build the fixed 10-question benchmark shared by baseline, corrupted and repaired runs."""
    test_set = [
        {
            "id": f"eval_{number:03d}",
            "question_type": question_type,
            "question": _question(question_type, row["title"]),
            "ground_truth": _ground_truth(question_type, row),
            "ground_truth_doc_ids": [row["paper_id"]],
        }
        for number, (question_type, row) in enumerate(plan_eval_items(df), start=1)
    ]
    write_json(Path(output_path), test_set)
    return test_set
