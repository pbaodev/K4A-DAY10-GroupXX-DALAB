# Corruption Comparison Report

## Metrics

| Metric | Baseline | Corrupted | Repaired | Δ (corrupted − baseline) |
| --- | --- | --- | --- | --- |
| retrieval_hit_rate | 1.0 | 0.7 | 1.0 | -0.30000000000000004 |
| mean_token_f1 | 1.0 | 0.654074074074074 | 1.0 | -0.34592592592592597 |
| judge_accuracy | 1.0 | 0.5 | 1.0 | -0.5 |
| mean_judge_score | 5 | 3.5 | 5 | -1.5 |
| samples | 10 | 10 | 10 | 0.0 |
| ragas.skipped | Set RUN_RAGAS=1 to enable the slower Ragas pass. | Set RUN_RAGAS=1 to enable the slower Ragas pass. | Set RUN_RAGAS=1 to enable the slower Ragas pass. | — |

## Great Expectations

Corrupted GX success: false

Repaired GX success: true

| Expectation | Column | Corrupted | Repaired |
| --- | --- | --- | --- |
| expect_table_row_count_to_be_between | — | pass | pass |
| expect_column_values_to_not_be_null | paper_id | pass | pass |
| expect_column_values_to_be_unique | paper_id | fail | pass |
| expect_column_values_to_not_be_null | title | pass | pass |
| expect_column_values_to_not_be_null | text_for_embedding | pass | pass |
| expect_column_value_lengths_to_be_between | summary | fail | pass |

## Freshness

| Signal | Corrupted | Repaired |
| --- | --- | --- |
| stale_ratio | 0.38095238095238093 | 0.041666666666666664 |
| is_fresh | false | true |
| stale_rows | 8 | 1 |
| total_rows | 21 | 24 |
| threshold_days | 180 | 180 |
| max_stale_ratio | 0.25 | 0.25 |

## Analysis

### Metric sụt mạnh nhất

Metric sụt mạnh nhất: mean_judge_score. mean_judge_score giảm từ 5.0 xuống 3.5 (Δ = -1.5).

### Expectation bắt được lỗi nào

- `expect_table_row_count_to_be_between` pass trên corrupted, nên không bắt được lỗi ở điều kiện này.
- `expect_column_values_to_not_be_null` (paper_id) pass trên corrupted, nên không bắt được lỗi ở điều kiện này.
- `expect_column_values_to_be_unique` (paper_id) fail trên corrupted, observed 4: bắt được trùng paper_id. Sau repair: pass.
- `expect_column_values_to_not_be_null` (title) pass trên corrupted, nên không bắt được lỗi ở điều kiện này.
- `expect_column_values_to_not_be_null` (text_for_embedding) pass trên corrupted, nên không bắt được lỗi ở điều kiện này.
- `expect_column_value_lengths_to_be_between` (summary) fail trên corrupted, observed 1: bắt được summary ngắn hơn 30 ký tự. Sau repair: pass.

### Silent failure

GX bắt được lỗi qua `expect_column_values_to_be_unique` (paper_id), `expect_column_value_lengths_to_be_between` (summary). Metric giảm: retrieval_hit_rate (Δ = -0.30000000000000004), mean_token_f1 (Δ = -0.34592592592592597), judge_accuracy (Δ = -0.5), mean_judge_score (Δ = -1.5). Các expectation vẫn pass (`expect_table_row_count_to_be_between`, `expect_column_values_to_not_be_null` (paper_id), `expect_column_values_to_not_be_null` (title), `expect_column_values_to_not_be_null` (text_for_embedding)) không phát hiện phần suy giảm đó.

### Repair phục hồi gì

- `retrieval_hit_rate`: corrupted 0.7 → repaired 1.0 (baseline 1.0); phục hồi về baseline.
- `mean_token_f1`: corrupted 0.654074074074074 → repaired 1.0 (baseline 1.0); phục hồi về baseline.
- `judge_accuracy`: corrupted 0.5 → repaired 1.0 (baseline 1.0); phục hồi về baseline.
- `mean_judge_score`: corrupted 3.5 → repaired 5.0 (baseline 5.0); phục hồi về baseline.
- `samples`: corrupted 10.0 → repaired 10.0 (baseline 10.0); không đổi khoảng cách tới baseline.
- Expectation `expect_column_values_to_be_unique` (paper_id) fail trên corrupted và pass sau repair.
- Expectation `expect_column_value_lengths_to_be_between` (summary) fail trên corrupted và pass sau repair.

### Freshness

Corrupted stale_ratio = 0.38095238095238093, is_fresh = false. Repaired stale_ratio = 0.041666666666666664, is_fresh = true. Repair làm giảm tỷ lệ bài quá hạn.

## Breakdown theo question_type

### Baseline

| question_type | samples | retrieval_hit_rate | mean_token_f1 |
| --- | --- | --- | --- |
| summary | 3 | 1.0 | 1.0 |
| authors | 3 | 1.0 | 1.0 |
| date | 2 | 1.0 | 1.0 |
| categories | 2 | 1.0 | 1.0 |

### Corrupted

| question_type | samples | retrieval_hit_rate | mean_token_f1 |
| --- | --- | --- | --- |
| summary | 3 | 0.6666666666666666 | 0.5135802469135803 |
| authors | 3 | 0.3333333333333333 | 1.0 |
| date | 2 | 1.0 | 0.0 |
| categories | 2 | 1.0 | 1.0 |

### Repaired

| question_type | samples | retrieval_hit_rate | mean_token_f1 |
| --- | --- | --- | --- |
| summary | 3 | 1.0 | 1.0 |
| authors | 3 | 1.0 | 1.0 |
| date | 2 | 1.0 | 1.0 |
| categories | 2 | 1.0 | 1.0 |
