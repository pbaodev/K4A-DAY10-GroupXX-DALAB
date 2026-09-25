# Phase 1 Report

## Source

| Field | Value |
| --- | --- |
| source_api | Crossref REST API |
| mode | snapshot |
| query | agentic retrieval augmented generation large language model |
| raw_records | 24 |
| clean_rows | 24 |
| run_date | 2026-09-25T10:39:36+00:00 |

## Metrics

| Metric | Value |
| --- | --- |
| retrieval_hit_rate | 1.0 |
| mean_token_f1 | 1.0 |
| judge_accuracy | 1.0 |
| mean_judge_score | 5 |
| samples | 10 |
| ragas | {"skipped": "Set RUN_RAGAS=1 to enable the slower Ragas pass."} |

## Data quality

GX success: true

| Expectation | Column | Result | Observed |
| --- | --- | --- | --- |
| expect_table_row_count_to_be_between | — | pass | 24 |
| expect_column_values_to_not_be_null | paper_id | pass | 0 |
| expect_column_values_to_be_unique | paper_id | pass | 0 |
| expect_column_values_to_not_be_null | title | pass | 0 |
| expect_column_values_to_not_be_null | text_for_embedding | pass | 0 |
| expect_column_value_lengths_to_be_between | summary | pass | 0 |

## Freshness

| Field | Value |
| --- | --- |
| stale_ratio | 0.041666666666666664 |
| is_fresh | true |
| stale_rows | 1 |
| total_rows | 24 |
| threshold_days | 180 |
| max_stale_ratio | 0.25 |
| latest_published | 2026-07-22 |
| oldest_published | 2026-03-28 |
