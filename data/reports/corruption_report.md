# Corruption & Repair Report — Baseline vs Corrupted vs Repaired

_Generated automatically by `script/run_corruption_flow.py` at 2026-09-25T09:38:38+00:00._

## 1. RAG Metrics — 3-State Comparison

| Metric | Baseline | Corrupted | Repaired | Δ Corrupted vs Baseline | Δ Repaired vs Baseline |
|---|---|---|---|---|---|
| Retrieval Hit Rate | 1.0000 | 0.7000 | 1.0000 | -0.3000 | +0.0000 |
| Mean Token F1 | 1.0000 | 0.8741 | 1.0000 | -0.1259 | +0.0000 |
| LLM Judge Accuracy | 1.0000 | 0.8000 | 1.0000 | -0.2000 | +0.0000 |
| Mean Judge Score (1-5) | 5 | 4.5000 | 5 | -0.5000 | +0.0000 |
| Judge verdict source | 10 LLM / 0 fallback | 10 LLM / 0 fallback | 10 LLM / 0 fallback | — | — |

> Judge verdicts marked *fallback* come from the token-F1 heuristic in `evaluation/metrics.py`, used when the LLM judge call fails (e.g. provider rate limits). Hit Rate and Token F1 are deterministic.

### Breakdown by question type (Hit Rate / Token F1)

| Question type | n | Baseline | Corrupted | Repaired |
|---|---|---|---|---|
| summary | 3 | 1.00 / 1.00 | 0.67 / 0.91 | 1.00 / 1.00 |
| authors | 3 | 1.00 / 1.00 | 0.67 / 1.00 | 1.00 / 1.00 |
| date | 2 | 1.00 / 1.00 | 0.50 / 0.50 | 1.00 / 1.00 |
| categories | 2 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |

## 2. Data Quality Gate (Great Expectations 1.x)

| Summary | Baseline | Corrupted | Repaired |
|---|---|---|---|
| Row count | 24 | 22 | 24 |
| GX suite success | ✅ True | ❌ False | ✅ True |
| Expectations passed | 9/9 | 5/9 | 9/9 |
| Gate passed (GX + freshness) | ✅ True | ❌ False | ✅ True |

| Expectation | Tier | Baseline | Corrupted | Repaired |
|---|---|---|---|---|
| `expect_table_row_count_to_be_between` | required | PASS (observed=24) | PASS (observed=22) | PASS (observed=24) |
| `expect_column_values_to_not_be_null` on `paper_id` | required | PASS | PASS | PASS |
| `expect_column_values_to_be_unique` on `paper_id` | required | PASS | FAIL (6 bad) | PASS |
| `expect_column_values_to_not_be_null` on `title` | required | PASS | PASS | PASS |
| `expect_column_value_lengths_to_be_between` on `title` | extra | PASS | FAIL (4 bad) | PASS |
| `expect_column_values_to_not_be_null` on `text_for_embedding` | required | PASS | PASS | PASS |
| `expect_column_value_lengths_to_be_between` on `summary` | required | PASS | FAIL (3 bad) | PASS |
| `expect_column_values_to_not_match_regex` on `summary` | extra | PASS | FAIL (4 bad) | PASS |
| `expect_column_values_to_not_be_null` on `age_days` | extra | PASS | PASS | PASS |

## 3. Freshness SLA

| Metric | Corrupted | Repaired |
|---|---|---|
| latest_published | 2026-06-12 | 2026-07-22 |
| oldest_published | 2025-04-18 | 2026-03-28 |
| stale_rows | 7 | 1 |
| total_rows | 22 | 24 |
| stale_ratio | 0.3182 | 0.0417 |
| median_age_days | 115.0000 | 110.5000 |
| is_fresh | ❌ False | ✅ True |

## 4. Injected Corruptions

Seed: `42` · rows before: 24 · rows after: 22

| # | Corruption | Rows affected | Test-set questions touched | Real-world failure it simulates | Caught by |
|---|---|---|---|---|---|
| 1 | `drop_latest_records` | 5 | eval_001 (summary), eval_002 (authors), eval_003 (date) | Incremental ingestion job failed; newest documents never arrive (stale knowledge). | Not caught by GX (row count still within 5-5000); visible as older latest_published and lower Hit Rate. |
| 2 | `blank_summary` | 3 | eval_010 (authors) | Upstream scraper/API returns an empty abstract field. | GX ExpectColumnValueLengthsToBeBetween(summary >= 30 chars). |
| 3 | `inject_noise` | 3 | eval_006 (authors), eval_008 (categories) | Broken encoding / OCR / HTML residue pollutes the abstract text. | GX ExpectColumnValuesToNotMatchRegex(summary, symbol runs) [extra check]. |
| 4 | `truncate_title` | 3 | none | Schema/column-width bug truncates titles, breaking exact title lookup. | GX ExpectColumnValueLengthsToBeBetween(title >= 8 chars) [extra check]. |
| 5 | `stale_date` | 6 | eval_004 (categories), eval_005 (summary) | An old snapshot is replayed / date parsing bug shifts publication dates into the past. | Freshness SLA (share of rows with age_days > 180 exceeds 25%). |
| 6 | `duplicate_rows` | 3 | eval_008 (categories), eval_009 (summary) | Non-idempotent retry appends the same batch twice (ghost/duplicate vectors). | GX ExpectColumnValuesToBeUnique(paper_id). |

Rows are chosen with a fixed seed, independently of the test set, so a corruption that touches no test question is still caught by the quality gate but does not move the RAG metrics.

## 5. Idempotent Repair

| Check | Result |
|---|---|
| trigger | auto: quality gate failed (expect_column_values_to_be_unique(paper_id), expect_column_value_lengths_to_be_between(title), expect_column_value_lengths_to_be_between(summary), expect_column_values_to_not_match_regex(summary)) |
| source | data/raw/crossref_records.json (immutable raw snapshot) |
| repaired_rows | 24 |
| idempotent (2 repair runs identical) | ✅ True |
| content matches baseline clean data | ✅ True |
| repaired GX success | ✅ True |
| repaired is_fresh | ✅ True |
| repaired sha256 | 46c483a2d95620b4 |

## 6. Analysis

- **Silent failure:** on corrupted data the pipeline still returned an answer for every question (no exception), yet Hit Rate fell by 0.30 and Token F1 by 0.13 versus the baseline.
- **Confident wrong source:** 3 question(s) were answered from a different paper than the ground truth, without any warning — eval_001: answered "An extended empirical study on tatic benchmarks fa" (expected "Static benchmarks fail to capture domain drift in "); eval_002: answered "Bao Do, Linh Ngo" (expected "Bao Do, Linh Ngo"); eval_003: answered "2026-06-02" (expected "2026-06-12").
- **Detection:** the GX gate flagged the corrupted batch with 4 failing expectation(s): `expect_column_values_to_be_unique(paper_id)`, `expect_column_value_lengths_to_be_between(title)`, `expect_column_value_lengths_to_be_between(summary)`, `expect_column_values_to_not_match_regex(summary)`.
- **Freshness:** stale ratio went from 0.0417 (repaired) to 0.3182 (corrupted); `is_fresh` = False on the corrupted data. Stale dates are invisible to schema checks, which is why a separate freshness SLA is needed.
- **Repair:** rebuilding from the raw snapshot gives GX success = True and retrieval/F1 metrics identical to the baseline.
