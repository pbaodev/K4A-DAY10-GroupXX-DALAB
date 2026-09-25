from __future__ import annotations

from typing import Any

import pandas as pd

from core.utils import compact_join, first_sentence, write_json

MIN_DOCUMENTS = 10
# 10 questions over the 4 business question types (question_type, count).
QUESTION_PLAN = [("summary", 3), ("authors", 3), ("date", 2), ("categories", 2)]

# Phrasings are aligned with `retrieval.qa._extract_answer`, which routes on these keywords,
# and quote the exact title so the QA layer can do an exact-title lookup.
QUESTION_TEMPLATES = {
    "summary": "What is the summary of the paper '{title}'?",
    "authors": "Who authored the paper '{title}'?",
    "date": "When was the paper '{title}' published?",
    "categories": "What categories does the paper '{title}' belong to?",
}


def _joined(row: pd.Series, joined_column: str, list_column: str) -> str:
    value = row.get(joined_column)
    if isinstance(value, str) and value:
        return value
    return compact_join(row.get(list_column) or [])


def _ground_truth(row: pd.Series, question_type: str) -> str:
    if question_type == "summary":
        return first_sentence(row["summary"])
    if question_type == "authors":
        return _joined(row, "authors_joined", "authors")
    if question_type == "date":
        return str(row["published"])[:10]
    return _joined(row, "categories_joined", "categories")


def build_test_set(df: pd.DataFrame, output_path) -> list[dict[str, Any]]:
    """Build a fixed 10-question benchmark (summary/authors/date/categories) from the clean corpus.

    Papers are picked deterministically (every other paper, newest first) so the same clean
    data always yields the same test set, and the set spans both recent and older papers.
    """
    total_questions = sum(count for _, count in QUESTION_PLAN)
    usable = df.dropna(subset=["paper_id", "title", "summary"])
    usable = usable[(usable["title"].str.len() > 0) & (usable["summary"].str.len() > 0)]
    usable = usable.drop_duplicates(subset="paper_id")
    # Titles containing a single quote would break the quoted-title lookup in the question.
    usable = usable[~usable["title"].str.contains("'", regex=False)]
    if len(usable) < MIN_DOCUMENTS:
        raise ValueError(f"Need at least {MIN_DOCUMENTS} clean documents to build a test set, got {len(usable)}.")

    ordered = usable.sort_values(["published", "paper_id"], ascending=[False, True]).reset_index(drop=True)
    step = max(1, len(ordered) // total_questions)
    picks = [ordered.iloc[(i * step) % len(ordered)] for i in range(total_questions)]

    # Round-robin the types (summary, authors, date, categories, summary, ...) so every slice of
    # the corpus, recent or old, is probed by several kinds of question.
    remaining = dict(QUESTION_PLAN)
    question_types: list[str] = []
    while len(question_types) < total_questions:
        for question_type, _ in QUESTION_PLAN:
            if remaining[question_type] > 0:
                question_types.append(question_type)
                remaining[question_type] -= 1
    test_set: list[dict[str, Any]] = []
    for number, (question_type, row) in enumerate(zip(question_types, picks, strict=True), start=1):
        test_set.append(
            {
                "id": f"eval_{number:03d}",
                "question_type": question_type,
                "question": QUESTION_TEMPLATES[question_type].format(title=row["title"]),
                "ground_truth": _ground_truth(row, question_type),
                "ground_truth_doc_ids": [str(row["paper_id"])],
            }
        )

    write_json(output_path, test_set)
    return test_set
