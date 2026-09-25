from __future__ import annotations

from datetime import date, timedelta
import math
from pathlib import Path
import random
import string
from typing import Any

import pandas as pd

from core.utils import write_json
from evaluation.testset import plan_eval_items
from ingestion.cleaning import compose_text_for_embedding

SEED = 42
DROP_LATEST_RATIO = 0.2
STALE_SHIFT_DAYS = 365
# Above the 25% freshness SLA even after duplicates inflate the row count.
STALE_TARGET_RATIO = 0.4
TRUNCATED_TITLE_CHARS = 6
NOISE_TOKENS = 6


def _noise(rng: random.Random) -> str:
    alphabet = string.ascii_letters + string.digits + "#@$%&*~^"
    return " ".join("".join(rng.choice(alphabet) for _ in range(rng.randint(4, 9))) for _ in range(NOISE_TOKENS))


def _eval_targets(df: pd.DataFrame) -> dict[str, list[str]]:
    targets: dict[str, list[str]] = {}
    try:
        items = plan_eval_items(df)
    except ValueError:
        return targets
    for question_type, row in items:
        bucket = targets.setdefault(question_type, [])
        if row["paper_id"] not in bucket:
            bucket.append(row["paper_id"])
    return targets


def _pick(preferred: list[str], available: list[str], used: set[str], count: int) -> list[str]:
    """Prefer test-set papers, fall back to other untouched rows so each scenario always fires."""
    chosen = [paper_id for paper_id in preferred if paper_id in available and paper_id not in used][:count]
    for paper_id in available:
        if len(chosen) >= count:
            break
        if paper_id not in used and paper_id not in chosen:
            chosen.append(paper_id)
    used.update(chosen)
    return chosen


def _entry(corruption_type: str, paper_ids: list[str], detail: str) -> dict[str, Any]:
    return {"type": corruption_type, "rows_affected": len(paper_ids), "paper_ids": paper_ids, "detail": detail}


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path) -> pd.DataFrame:
    """Inject six deterministic data faults into a copy of the clean dataframe and log them."""
    rng = random.Random(SEED)
    targets = _eval_targets(df)
    frame = (
        df.drop_duplicates(subset=["paper_id"], keep="first")
        .sort_values(by=["published", "paper_id"], ascending=[False, True], kind="stable")
        .reset_index(drop=True)
        .copy()
    )
    log: list[dict[str, Any]] = []

    drop_count = max(1, round(len(frame) * DROP_LATEST_RATIO))
    dropped = frame["paper_id"].head(drop_count).tolist()
    frame = frame.iloc[drop_count:].reset_index(drop=True)
    log.append(_entry("drop_latest", dropped, f"Dropped the {drop_count} newest records ({DROP_LATEST_RATIO:.0%}) by published date."))

    available = frame["paper_id"].tolist()
    used: set[str] = set()
    row_of = {paper_id: position for position, paper_id in enumerate(available)}

    blanked = _pick(targets.get("summary", []), available, used, 1)
    for paper_id in blanked:
        frame.at[row_of[paper_id], "summary"] = ""
    log.append(_entry("blank_summary", blanked, "Set summary to an empty string."))

    noised = _pick(targets.get("summary", []), available, used, 1)
    for paper_id in noised:
        position = row_of[paper_id]
        frame.at[position, "summary"] = f"{_noise(rng)} {frame.at[position, 'summary']}"
    log.append(_entry("inject_noise", noised, f"Prefixed summary with {NOISE_TOKENS} random junk tokens (seed={SEED})."))

    truncated = _pick(targets.get("authors", []), available, used, 1)
    for paper_id in truncated:
        position = row_of[paper_id]
        frame.at[position, "title"] = str(frame.at[position, "title"])[:TRUNCATED_TITLE_CHARS].rstrip()
    log.append(_entry("truncate_title", truncated, f"Cut title down to {TRUNCATED_TITLE_CHARS} characters."))

    stale_count = max(1, math.ceil(len(frame) * STALE_TARGET_RATIO))
    date_targets = [paper_id for paper_id in targets.get("date", []) if paper_id in row_of and paper_id not in used]
    fillers = [paper_id for paper_id in available if paper_id not in used and paper_id not in date_targets]
    rng.shuffle(fillers)
    staled = _pick(date_targets + fillers, available, used, stale_count)
    for paper_id in staled:
        position = row_of[paper_id]
        shifted = date.fromisoformat(str(frame.at[position, "published"])) - timedelta(days=STALE_SHIFT_DAYS)
        frame.at[position, "published"] = shifted.isoformat()
        frame.at[position, "age_days"] = int(frame.at[position, "age_days"]) + STALE_SHIFT_DAYS
    log.append(_entry("stale_date", staled, f"Moved published back {STALE_SHIFT_DAYS} days and increased age_days to match."))

    duplicated = _pick(targets.get("categories", []), available, used, 2)
    log.append(_entry("duplicate_rows", duplicated, "Appended a second copy of each row with the same paper_id."))

    frame["summary_chars"] = frame["summary"].fillna("").astype(str).str.len()
    frame["text_for_embedding"] = [compose_text_for_embedding(row) for row in frame.to_dict(orient="records")]
    if duplicated:
        copies = frame[frame["paper_id"].isin(duplicated)]
        frame = pd.concat([frame, copies], ignore_index=True)

    write_json(Path(output_log_path), log)
    return frame.reset_index(drop=True)
