from __future__ import annotations

from datetime import timedelta
import math
import random
from typing import Any

import pandas as pd

from core.utils import now_utc, write_json
from ingestion.cleaning import add_derived_columns

DEFAULT_SEED = 42
DROP_LATEST_RATIO = 0.20
BLANK_SUMMARY_RATIO = 0.15
NOISE_RATIO = 0.15
TRUNCATE_TITLE_RATIO = 0.15
STALE_RATIO = 0.30
DUPLICATE_RATIO = 0.15
TRUNCATED_TITLE_CHARS = 7
STALE_SHIFT_DAYS = 365
NOISE_TOKENS = ["#@$", "~^%", "&*#!", "<<##>>", "@@~~", "%$#@"]


def _count(ratio: float, total: int) -> int:
    return min(total, max(1, math.ceil(ratio * total))) if total else 0


def _inject_noise(text: str, rng: random.Random) -> str:
    # Interleave garbage tokens every few words so the first sentence (the answer span) is polluted too.
    words = text.split()
    noisy: list[str] = []
    for position, word in enumerate(words, start=1):
        noisy.append(word)
        if position % 3 == 0:
            noisy.append(rng.choice(NOISE_TOKENS))
    return " ".join(noisy)


def _step(kind: str, df: pd.DataFrame, rows: list[int], simulates: str, detected_by: str, **params: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "rows_affected": len(rows),
        "paper_ids": [str(df.at[row, "paper_id"]) for row in rows],
        "params": params,
        "simulates": simulates,
        "detected_by": detected_by,
    }


def corrupt_clean_dataframe(df: pd.DataFrame, output_log_path, seed: int = DEFAULT_SEED) -> pd.DataFrame:
    """Apply 6 realistic corruptions to a clean dataframe (deterministic for a given seed) and log them.

    The input dataframe is never modified; the returned copy has `text_for_embedding` and the
    other helper columns rebuilt so the corruption flows all the way into the vector index.
    """
    rng = random.Random(seed)
    corrupted = df.copy().reset_index(drop=True)
    corrupted["published"] = pd.to_datetime(corrupted["published"]).dt.strftime("%Y-%m-%d")
    rows_before = len(corrupted)
    log: list[dict[str, Any]] = []

    # 1. Drop latest records: the newest papers silently never make it into the corpus.
    latest = corrupted.sort_values(["published", "paper_id"], ascending=[False, True]).index[
        : _count(DROP_LATEST_RATIO, rows_before)
    ].tolist()
    log.append(
        _step(
            "drop_latest_records", corrupted, latest,
            "Incremental ingestion job failed; newest documents never arrive (stale knowledge).",
            "Not caught by GX (row count still within 5-5000); visible as older latest_published and lower Hit Rate.",
            ratio=DROP_LATEST_RATIO,
        )
    )
    corrupted = corrupted.drop(index=latest).reset_index(drop=True)

    # 2-4 hit disjoint rows so each failure mode is measured in isolation.
    candidates = list(corrupted.index)
    rng.shuffle(candidates)
    n_blank = _count(BLANK_SUMMARY_RATIO, len(corrupted))
    n_noise = _count(NOISE_RATIO, len(corrupted))
    n_trunc = _count(TRUNCATE_TITLE_RATIO, len(corrupted))
    blank_rows = sorted(candidates[:n_blank])
    noise_rows = sorted(candidates[n_blank : n_blank + n_noise])
    trunc_rows = sorted(candidates[n_blank + n_noise : n_blank + n_noise + n_trunc])

    # 2. Blank summary: scraper returned an empty abstract.
    log.append(
        _step(
            "blank_summary", corrupted, blank_rows,
            "Upstream scraper/API returns an empty abstract field.",
            "GX ExpectColumnValueLengthsToBeBetween(summary >= 30 chars).",
            ratio=BLANK_SUMMARY_RATIO,
        )
    )
    corrupted.loc[blank_rows, "summary"] = ""

    # 3. Inject noise: encoding/OCR garbage mixed into the abstract.
    log.append(
        _step(
            "inject_noise", corrupted, noise_rows,
            "Broken encoding / OCR / HTML residue pollutes the abstract text.",
            "GX ExpectColumnValuesToNotMatchRegex(summary, symbol runs) [extra check].",
            ratio=NOISE_RATIO, tokens=NOISE_TOKENS, every_n_words=3,
        )
    )
    for row in noise_rows:
        corrupted.at[row, "summary"] = _inject_noise(str(corrupted.at[row, "summary"]), rng)

    # 4. Truncate title: a field-length bug cuts titles to a few characters.
    log.append(
        _step(
            "truncate_title", corrupted, trunc_rows,
            "Schema/column-width bug truncates titles, breaking exact title lookup.",
            "GX ExpectColumnValueLengthsToBeBetween(title >= 8 chars) [extra check].",
            ratio=TRUNCATE_TITLE_RATIO, max_chars=TRUNCATED_TITLE_CHARS,
        )
    )
    for row in trunc_rows:
        corrupted.at[row, "title"] = str(corrupted.at[row, "title"])[:TRUNCATED_TITLE_CHARS]

    # 5. Stale date: publication dates regress by a year (wrong timezone/epoch or old snapshot replayed).
    stale_rows = sorted(rng.sample(list(corrupted.index), _count(STALE_RATIO, len(corrupted))))
    log.append(
        _step(
            "stale_date", corrupted, stale_rows,
            "An old snapshot is replayed / date parsing bug shifts publication dates into the past.",
            "Freshness SLA (share of rows with age_days > 180 exceeds 25%).",
            ratio=STALE_RATIO, shift_days=STALE_SHIFT_DAYS,
        )
    )
    for row in stale_rows:
        shifted = pd.Timestamp(corrupted.at[row, "published"]) - timedelta(days=STALE_SHIFT_DAYS)
        corrupted.at[row, "published"] = shifted.strftime("%Y-%m-%d")
        corrupted.at[row, "age_days"] = int(corrupted.at[row, "age_days"]) + STALE_SHIFT_DAYS

    # 6. Duplicate rows: a retried batch is appended twice.
    dup_rows = sorted(rng.sample(list(corrupted.index), _count(DUPLICATE_RATIO, len(corrupted))))
    log.append(
        _step(
            "duplicate_rows", corrupted, dup_rows,
            "Non-idempotent retry appends the same batch twice (ghost/duplicate vectors).",
            "GX ExpectColumnValuesToBeUnique(paper_id).",
            ratio=DUPLICATE_RATIO,
        )
    )
    corrupted = pd.concat([corrupted, corrupted.loc[dup_rows]], ignore_index=True)

    # 7. Rebuild the embed text so every corruption reaches the vector store.
    corrupted = add_derived_columns(corrupted)
    corrupted["age_days"] = corrupted["age_days"].astype(int)

    # 8. Persist the corruption log.
    write_json(
        output_log_path,
        {
            "generated_at": now_utc().isoformat(),
            "seed": seed,
            "rows_before": rows_before,
            "rows_after": len(corrupted),
            "corruption_types": len(log),
            "corruptions": log,
        },
    )
    return corrupted
