# Phase 1 Report — Baseline Data Pipeline

_Generated automatically by `script/run_phase1.py` at 2026-09-25T09:37:49+00:00._

## 1. Source & Lineage

| Item | Value |
|---|---|
| Source | Crossref REST API |
| Mode | offline snapshot |
| Query | agentic retrieval augmented generation large language model |
| Raw response | data/raw/crossref_response.json |
| Raw records | data/raw/crossref_records.json (24 records) |
| Clean rows | 24 |
| Run date (UTC) | 2026-09-25 |
| Embedding model | sentence-transformers/all-MiniLM-L6-v2 |
| Chroma collection | papers-baseline (24 vectors) |
| Top-k | 4 |

## 2. Data Quality Gate (Great Expectations 1.x)

- Engine: great_expectations 1.18.0 (ephemeral context)
- Suite success: **✅ True** (9/9 expectations passed)
- Gate passed (GX + freshness): **✅ True**

| Expectation | Tier | Baseline |
|---|---|---|
| `expect_table_row_count_to_be_between` | required | PASS (observed=24) |
| `expect_column_values_to_not_be_null` on `paper_id` | required | PASS |
| `expect_column_values_to_be_unique` on `paper_id` | required | PASS |
| `expect_column_values_to_not_be_null` on `title` | required | PASS |
| `expect_column_value_lengths_to_be_between` on `title` | extra | PASS |
| `expect_column_values_to_not_be_null` on `text_for_embedding` | required | PASS |
| `expect_column_value_lengths_to_be_between` on `summary` | required | PASS |
| `expect_column_values_to_not_match_regex` on `summary` | extra | PASS |
| `expect_column_values_to_not_be_null` on `age_days` | extra | PASS |

## 3. Freshness SLA

Rule: alert when more than 25% of papers are older than 180 days.

| Metric | Value |
|---|---|
| latest_published | 2026-07-22 |
| oldest_published | 2026-03-28 |
| stale_rows | 1 |
| total_rows | 24 |
| stale_ratio | 0.0417 |
| median_age_days | 110.5000 |
| is_fresh | ✅ True |

## 4. Baseline RAG Evaluation

Samples: 10

| Metric | Baseline |
|---|---|
| Retrieval Hit Rate | 1.0000 |
| Mean Token F1 | 1.0000 |
| LLM Judge Accuracy | 1.0000 |
| Mean Judge Score (1-5) | 5 |
| Judge verdict source | 10 LLM / 0 fallback |

| Question type | n | Hit Rate | Token F1 |
|---|---|---|---|
| summary | 3 | 1.00 | 1.00 |
| authors | 3 | 1.00 | 1.00 |
| date | 2 | 1.00 | 1.00 |
| categories | 2 | 1.00 | 1.00 |

Ragas: `{'skipped': 'Set RUN_RAGAS=1 to enable the slower Ragas pass.'}`

## 5. Notes

- The quality gate runs **before** indexing: a failing GX suite stops Phase 1 so bad data never reaches ChromaDB.
- A freshness breach does not block indexing; it is surfaced as an alert (`is_fresh = False`).
- All numbers above are read from the artifacts produced in this run (`data/results/baseline_metrics.json`, `data/quality/*.json`).
