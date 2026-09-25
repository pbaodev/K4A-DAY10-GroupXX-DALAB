# Group Report — Day 10: Data Pipeline & Data Observability

> Dùng mẫu này cho báo cáo chung của nhóm 3–5 thành viên. Thay toàn bộ nội dung trong dấu `[ ]` bằng thông tin và kết quả thực tế. Xóa các dòng hướng dẫn không còn cần thiết trước khi nộp.

## 1. Thông tin bài nộp

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Khóa/Lớp         | K4 (K4-L3A-DAY10)              |
| Tên nhóm         | DALAB     |
| Repository         | https://github.com/pbaodev/K4A-DAY10-GroupXX-DALAB |
| Ngày hoàn thành | 2026-09-25               |

### Thành viên và phân công

| STT | Họ và tên | MSSV | Vai trò chính | Module/deliverable sở hữu |
| --: | --- | --- | --- | --- |
| 1 | Phan Duy Bảo | 2A202602767 | Trưởng nhóm / Pipeline Integrator | `src/pipelines/phase1.py`, `src/pipelines/corruption_flow.py`, `src/core/`, artifacts `data/` |
| 2 | Trang Phước Hoàng Minh | 2A202602690 | Data Foundation & Recovery | `src/ingestion/crossref.py`, `src/ingestion/cleaning.py`, `src/ingestion/repair.py` |
| 3 | Vũ Quốc Bảo | 2A202602829 | RAG & Evaluation | `src/evaluation/testset.py`, `src/ingestion/corruption.py`, `src/retrieval/` (ChromaDB, QA agent) |
| 4 | Lê Gia Bảo | 2A202602887 | Observability & Reporting | `src/observability/quality.py` (GX 1.x, Freshness SLA), `src/observability/reporting.py` |
| 5 | — | — | — | — |

## 2. Tóm tắt kết quả

Viết từ 150–250 từ, trả lời ngắn gọn:

- Nhóm đã hoàn thành những phần nào?
- Baseline pipeline đã tạo ra các artifact nào?
- Corruption nào ảnh hưởng rõ nhất đến data quality hoặc agent?
- Repair đã phục hồi được chỉ số nào?
- Blocker hoặc giới hạn quan trọng nhất còn lại là gì?

**Tóm tắt của nhóm:**

**Phạm vi hoàn thành:** Nhóm hoàn thành đủ 7 tầng của pipeline: ingestion Crossref (có fallback snapshot), cleaning, quality gate Great Expectations 1.x kèm Freshness SLA, index MiniLM + ChromaDB, evaluation, corruption, và repair kèm báo cáo đối chiếu. Cả `run_phase1.py` và `run_corruption_flow.py` đều chạy với exit code 0. CI (GitHub Actions) đạt 40/40 test, coverage 96%.

**Artifact baseline:**
- Dữ liệu sạch `papers_clean.csv/json` (24 dòng).
- Collection `papers-baseline` (24 docs).
- `test_set.json` (10 câu hỏi).
- `baseline_metrics.json`: hit rate, token F1 và judge accuracy đều bằng 1.000.
- Quality report pass 6/6 expectations, freshness `is_fresh=True`.
- Báo cáo `phase1_report.md`.

**Tác động của corruption:** Tiêm 6 loại lỗi làm quality gate fail (trùng `paper_id`, `summary` rỗng) và freshness chuyển sang stale (`stale_ratio` 0.381, ngưỡng 0.25). Agent suy giảm: hit rate 0.700, token F1 0.654, judge accuracy 0.500.
- Lỗi nguy hiểm nhất là `stale_date`: retrieval vẫn tìm đúng bài, nhưng agent trả lời sai năm một cách tự tin (F1 = 0). Đây đúng là một silent failure mà GX không bắt được, chỉ freshness mới bắt được.

**Repair:** Dựng lại dữ liệu từ `crossref_records.json`, đưa mọi chỉ số (hit rate, F1, judge, quality, freshness) về đúng bằng baseline.

**Giới hạn chính:**
- Dữ liệu chạy ở chế độ snapshot 24 bài, và corpus có nhiều cặp bài gần trùng nội dung.
- Metric hiện tại chấm "đúng" cả những câu trả lời lấy từ sai tài liệu.

## 3. Kiến trúc và luồng dữ liệu

### Luồng end-to-end

Điều chỉnh sơ đồ dưới đây nếu cách triển khai thực tế của nhóm khác starter:

```text
Crossref API (REFRESH_SOURCE=1) hoặc snapshot data/raw/crossref_response.json (mặc định)
    -> raw response/raw records          data/raw/crossref_response.json, crossref_records.json
    -> cleaning và data modeling         data/clean/papers_clean.csv/json
    -> quality gate GX 1.x + freshness   data/quality/baseline_quality_report.json, freshness_report.json (fail -> dừng, không index)
    -> embedding + ChromaDB index        collection papers-baseline, data/embeddings/papers_embeddings.json
    -> evaluation baseline               data/eval/test_set.json -> data/results/baseline_metrics.json
    -> phase 1 report                    data/reports/phase1_report.md
    -> corruption (6 kịch bản, seed 42)  data/results/corruption_log.json, data/clean/papers_clean_corrupted.*
    -> quality/freshness corrupted       (FAIL, vẫn index để đo silent failure)
    -> re-index và re-evaluate           collection papers-corrupted -> corrupted_metrics.json
    -> repair từ raw records             data/clean/papers_clean_repaired.* -> collection papers-repaired -> repaired_metrics.json
    -> comparison report                 data/reports/corruption_report.md
```

### Trách nhiệm của từng khối

| Khối             | Input          | Xử lý chính             | Output/artifact          | Owner          |
| ----------------- | -------------- | -------------------------- | ------------------------ | -------------- |
| Ingestion         | Crossref REST API `/works` hoặc snapshot `crossref_response.json` | Gọi API khi `REFRESH_SOURCE=1`, retry 3 lần với HTTP 429/503 và lỗi mạng, fallback về snapshot; parse DOI, title, abstract, authors, subject, published   | `data/raw/crossref_response.json`, `data/raw/crossref_records.json` | Trang Phước Hoàng Minh (M2) |
| Cleaning          | `list[PaperRecord]`, `run_date`        | Bỏ thẻ JATS/HTML, chuẩn hóa khoảng trắng, ngày về `YYYY-MM-DD`, tính `age_days`, bỏ record thiếu `paper_id`/title/ngày, loại trùng theo `paper_id`, sort ổn định     | `data/clean/papers_clean.csv`, `papers_clean.json` | Trang Phước Hoàng Minh (M2) |
| Embedding/index   | Clean dataframe        | `sentence-transformers/all-MiniLM-L6-v2`, ChromaDB persistent, cosine, 3 collection tách biệt       | `data/chroma/`, `data/embeddings/*.json` | Vũ Quốc Bảo (M3) |
| Evaluation        | Clean dataframe, index        | Test set 10 câu (4 loại) sinh deterministic; hit rate, token F1, LLM judge     | `data/eval/test_set.json`, `data/results/*_metrics.json`, `*_answers.json` | Vũ Quốc Bảo (M3) |
| Observability     | Dataframe từng trạng thái        | GX 1.x ephemeral context với 6 expectation (thuộc 4 loại bắt buộc); Freshness SLA (`age_days > 180`, tối đa 25%) | `data/quality/{baseline,corrupted,repaired}_quality_report.json`, `freshness_report*.json` | Lê Gia Bảo (M4) |
| Corruption/repair | Clean dataframe; raw records        | 6 kịch bản lỗi deterministic nhắm vào paper trong test set; repair dựng lại từ raw records    | `data/results/corruption_log.json`, `data/clean/papers_clean_{corrupted,repaired}.*` | Vũ Quốc Bảo (M3) — corruption; Trang Phước Hoàng Minh (M2) — repair |
| Orchestration     | Settings, các module trên        | Phase 1: ingest → clean → gate → index → evaluate → report. Corruption flow: corrupt → check → evaluate → repair → check → evaluate → so sánh           | `data/reports/phase1_report.md`, `data/reports/corruption_report.md`        | Phan Duy Bảo (M1) |

## 4. Cách tái hiện kết quả

### Cấu hình không chứa secret

| Biến/cấu hình             | Giá trị sử dụng |
| ---------------------------- | ------------------- |
| `LLM_PROVIDER`             | `openai` (CI dùng `mock`)         |
| `LLM_MODEL`                | `gpt-4o-mini`         |
| Embedding model              | `sentence-transformers/all-MiniLM-L6-v2`         |
| Số lượng Crossref records | 24 (`max_results=24`, chế độ snapshot)         |
| Retrieval`top_k`           | 4         |
| Freshness threshold          | 180 ngày; tối đa 25% bài quá hạn         |
| Random seed, nếu có        | 42 (`random.Random(42)` trong `corruption.py`)         |

Không dán nội dung API key hoặc file `.env` vào báo cáo.

### Lệnh cài đặt

Chỉ giữ lại cách nhóm đã dùng.

```bash
uv sync
```

Hoặc:

```bash
python -m pip install -e .
```

### Lệnh chạy

Baseline:

```bash
uv run python script/run_phase1.py
```

Hoặc với môi trường `pip` đã kích hoạt:

```bash
python script/run_phase1.py
```

Corruption flow:

```bash
uv run python script/run_corruption_flow.py
```

Hoặc với môi trường `pip` đã kích hoạt:

```bash
python script/run_corruption_flow.py
```

### Kết quả tái hiện

| Lệnh             | Trạng thái                                    | Thời điểm chạy gần nhất | Bằng chứng                         |
| ----------------- | ----------------------------------------------- | ----------------------------- | ------------------------------------ |
| Baseline pipeline | Thành công (exit code 0) | 2026-09-25 10:39 UTC (`run_date` trong `phase1_report.md`)                  | `data/reports/phase1_report.md`, `data/results/baseline_metrics.json`, collection `papers-baseline` (24 docs) |
| Corruption flow   | Thành công (exit code 0) | 2026-09-25                  | `data/reports/corruption_report.md`, `corrupted_metrics.json`, `repaired_metrics.json`. Chạy 2 lần: mọi file metrics, quality, log và report giống hệt; chỉ phần giải thích bằng chữ của LLM judge khác |

## 5. Ingestion, cleaning và data contract

### Nguồn dữ liệu

| Thuộc tính                | Giá trị                             |
| --------------------------- | ------------------------------------- |
| Source                      | Crossref REST API `https://api.crossref.org/works`; lần chạy nộp bài dùng snapshot `data/raw/crossref_response.json` (`mode=snapshot`) |
| Query/filter                | `query=agentic retrieval augmented generation large language model`; `filter=from-pub-date:<run_date − 180 ngày>,has-abstract:true`; `rows=24`                  |
| Thời điểm lấy dữ liệu | Snapshot đọc lúc 2026-09-25T10:39:36+00:00                           |
| Số record nhận được    | 24 raw items → 24 records → 24 dòng sạch                         |
| Cơ chế retry/backoff      | Tối đa 3 lần; retry khi HTTP 429/503, lỗi mạng hoặc JSON lỗi; nghỉ 0.5 s × số lần thử; timeout 15 s; hết lượt thì fallback về snapshot, không ghi đè file raw                       |

### Raw và clean schema

| Trường        | Kiểu dữ liệu | Bắt buộc?  | Ý nghĩa   | Xử lý khi thiếu/sai |
| --------------- | --------------- | ------------ | ----------- | ---------------------- |
| `paper_id` | `str`         | Có | DOI, khóa định danh duy nhất | Thiếu → bỏ record; trùng → giữ bản đầu |
| `title` | `str`         | Có | Tiêu đề đã chuẩn hóa khoảng trắng | Rỗng → bỏ record |
| `summary` | `str`         | Có (GX ≥ 30 ký tự) | Abstract đã bỏ thẻ JATS/HTML | Thiếu → `""` (không `None`); quality gate bắt nếu < 30 ký tự |
| `authors`, `categories` | `list[str]`         | Không | Danh sách tác giả / subject | Bỏ phần tử rỗng |
| `authors_joined`, `categories_joined` | `str`         | Không | Nối bằng `", "`, dùng làm metadata Chroma và đáp án | Rỗng → `""` |
| `published`, `updated` | `str` `YYYY-MM-DD`         | `published`: Có | Ngày xuất bản / cập nhật | Không parse được `published` → bỏ record; thiếu `updated` → lấy `published` |
| `age_days` | `int`         | Có | `(run_date − published).days` | Tính lại mỗi lần chạy |
| `summary_chars` | `int`         | Có | Độ dài `summary` | Tính lại sau cleaning/corruption |
| `text_for_embedding` | `str`         | Có | Văn bản 5 dòng đưa vào embedding | Sinh bằng `compose_text_for_embedding` |
| `primary_category`, `abs_url`, `pdf_url`, `comment` | `str`         | Không | Metadata phụ | Thiếu → `""`; `primary_category` fallback về category đầu tiên |

### Quy tắc cleaning

| Quy tắc                                 | Quality dimension liên quan | Số record bị tác động | Cách xác minh      |
| ---------------------------------------- | ---------------------------- | -------------------------: | -------------------- |
| Bỏ thẻ JATS/HTML (`<jats:p>`…) khỏi abstract, unescape HTML | Validity                  |              24 | 24/24 raw abstract có thẻ; 0 dòng còn `<` trong `papers_clean.json` |
| Bỏ record thiếu `paper_id`, title hoặc ngày xuất bản hợp lệ | Completeness                     |              0 | 24 records → 24 dòng sạch; GX `not_null` pass 24/24 |
| Loại trùng theo `paper_id` (giữ bản đầu) | Uniqueness                     |              0 | GX `expect_column_values_to_be_unique` pass, `unexpected_count=0` |
| Chuẩn hóa ngày về `YYYY-MM-DD`, tính `age_days` | Consistency / Timeliness                     |              24 | `age_days` từ 65 đến 181; freshness `stale_rows=1` |
| Sort `published` giảm dần rồi `paper_id`, `reset_index` | Consistency (tái lập)                     |              24 | Chạy lại cho CSV/JSON giống hệt từng byte (repair = baseline) |

Giải thích cách nhóm tạo `text_for_embedding`, document ID và `age_days`:

- **`text_for_embedding`:** hàm `compose_text_for_embedding(row)` ghép 5 dòng `Title / Authors / Published / Categories / Summary`. Cả cleaning và corruption đều dùng chung hàm này, nên văn bản được embed luôn phản ánh đúng dữ liệu của trạng thái đó.
- **Document ID:** `paper_id` là DOI, dùng làm `ground_truth_doc_ids` trong test set. Trong Chroma, mỗi record có id `"{paper_id}::{vị trí}"`, nhờ đó các dòng bị nhân bản ở trạng thái corrupted không xung đột id nhưng vẫn cùng `paper_id`.
- **`age_days`:** bằng `(run_date − published).days`, với `run_date = now_utc()` được tạo đúng **một lần** mỗi lần chạy và truyền cho mọi bước.

## 6. Evaluation setup

| Thành phần                             | Cấu hình thực tế          |
| ---------------------------------------- | ----------------------------- |
| Số câu hỏi                            | 10 (`eval_001` … `eval_010`)                 |
| Các`question_type`                    | `summary` (3), `authors` (3), `date` (2), `categories` (2)                  |
| Ground-truth document ID                 | DOI của paper được hỏi. Paper chọn deterministic (sort mới → cũ, lấy 10 vị trí cách đều, luôn gồm bài mới nhất); `ground_truth` lấy từ đúng cột mà `qa.py` trích ra     |
| Embedding model                          | `sentence-transformers/all-MiniLM-L6-v2`                  |
| Vector store/collection                  | ChromaDB persistent `data/chroma`, cosine; `papers-baseline` / `papers-corrupted` / `papers-repaired`                 |
| Retrieval`top_k`                       | 4                   |
| LLM provider/model                       | `openai` / `gpt-4o-mini` (LLM judge và agent demo); CI dùng `mock`                   |
| Test set dùng chung cho ba trạng thái | `data/eval/test_set.json` (sha256 `3541bfb96efb…`) |

Giải thích vì sao test set được giữ nguyên khi đánh giá baseline, corrupted và repaired:

Test set được sinh **một lần** từ dữ liệu sạch ở phase 1. `run_corruption_flow.py` chỉ đọc lại file này, không sinh mới. Như vậy biến số duy nhất giữa 3 lần đo là dữ liệu trong index.

Nếu sinh lại test set từ dữ liệu corrupted, `ground_truth` sẽ lấy luôn giá trị đã hỏng (ví dụ ngày bị lùi 365 ngày). Agent khi đó "trả lời đúng" theo dữ liệu sai, metric vẫn cao, và silent failure bị che mất.

## 7. Kết quả baseline

### Artifact checklist

| Artifact                 | Đường dẫn thực tế                | Trạng thái | Ghi chú   |
| ------------------------ | -------------------------------------- | ------------ | ---------- |
| Raw response/records     | `data/raw/`                          | Có | `crossref_response.json` (24 items), `crossref_records.json` (24 records) |
| Cleaned dataset          | `data/clean/`                        | Có | `papers_clean.csv/json` 24 dòng; kèm bản `_corrupted` và `_repaired` |
| Embedding manifest/index | `data/embeddings/`                   | Có | 3 manifest, `persist_path` tương đối `data/chroma`; `data/chroma/` có đúng 3 collection |
| Evaluation set           | `data/eval/`                         | Có | `test_set.json` 10 câu |
| Baseline metrics         | `data/results/baseline_metrics.json` | Có | Kèm `baseline_answers.json`, `agent_demo_answers.json` |
| Quality/freshness        | `data/quality/`                      | Có | Quality report cho baseline/corrupted/repaired; `freshness_report.json`, `_corrupted`, `_repaired` |
| Baseline report          | `data/reports/phase1_report.md`      | Có | Gồm Source, Metrics, Data quality, Freshness |

### Baseline metrics

| Metric                 |       Giá trị | Diễn giải                             |
| ---------------------- | --------------: | --------------------------------------- |
| `retrieval_hit_rate` |     1.000 | Cả 10 câu đều có DOI đúng trong top-4; tiêu đề trong câu hỏi cho phép tra cứu chính xác (exact lookup)  |
| `mean_token_f1`      |     1.000 | Câu trả lời trùng khớp `ground_truth`, vì bộ đề được thiết kế theo đúng cách `qa.py` trích câu trả lời                           |
| `judge_accuracy`     |     1.000 | LLM judge `gpt-4o-mini` chấm đúng 10/10                           |
| `mean_judge_score`   |     5.000 | Mọi câu đạt 5/5; đây là mốc trần để đo suy giảm                           |
| Ragas, nếu có        | N/A | Không bật (`RUN_RAGAS` không đặt) để giữ thời gian chạy và chi phí LLM thấp; 4 metric trên đã đủ để so sánh 3 trạng thái |

## 8. Data quality và freshness

### Quality checks

| Check        | Quality dimension | Ngưỡng/kỳ vọng | Kết quả baseline      | Bằng chứng |
| ------------ | ----------------- | ------------------ | ----------------------- | ------------ |
| `ExpectTableRowCountToBeBetween` | Volume/Completeness       | 5 – 5000 dòng         | Pass — 24 dòng | `data/quality/baseline_quality_report.json`   |
| `ExpectColumnValuesToNotBeNull` (`paper_id`, `title`, `text_for_embedding`) | Completeness       | 0 giá trị null         | Pass — 0/24 null ở cả 3 cột | `data/quality/baseline_quality_report.json`   |
| `ExpectColumnValuesToBeUnique` (`paper_id`) | Uniqueness       | 0 trùng lặp         | Pass — 0 trùng | `data/quality/baseline_quality_report.json`   |
| `ExpectColumnValueLengthsToBeBetween` (`summary`) | Validity       | ≥ 30 ký tự         | Pass — 0 vi phạm (ngắn nhất 193 ký tự) | `data/quality/baseline_quality_report.json`   |

### Freshness

| Thuộc tính               | Giá trị                           |
| -------------------------- | ----------------------------------- |
| Freshness được đo tại | Clean dataset (cột `age_days`), trước khi index; ghi ra `data/quality/freshness_report.json`            |
| Timestamp mới nhất       | `latest_published` = 2026-07-22 (cũ nhất 2026-03-28)                         |
| Ngưỡng freshness         | Bài quá hạn khi `age_days > 180`; dataset stale khi tỉ lệ bài quá hạn > 25%                         |
| Trạng thái baseline      | Fresh (`is_fresh=True`)               |
| Lý do                     | 1/24 bài quá hạn (`stale_ratio` = 0.042 ≤ 0.25); bài 2026-03-28 có `age_days` = 181 tại `run_date` 2026-09-25 |

## 9. Corruption scenarios và repair

| Corruption         | Cách tạo | Record bị tác động | Quality signal kỳ vọng | Tác động thực tế | Cách repair   |
| ------------------ | ---------- | ---------------------: | ------------------------ | --------------------- | -------------- |
| `drop_latest` | Bỏ 20% bài mới nhất theo `published`  |          5 | Số dòng giảm (24 → 21), bài mới biến mất | Retrieval MISS ở `eval_001`, `eval_002`; row count vẫn trong 5–5000 nên GX không bắt | Dựng lại từ `crossref_records.json` |
| `blank_summary` | `summary = ""`  |          1 | GX độ dài `summary` fail | GX fail (observed 1); `eval_005` hit nhưng câu trả lời rỗng, F1 0.00, judge 1 điểm | Dựng lại từ raw |
| `inject_noise` | Chèn 6 token ký tự rác vào đầu `summary` (seed 42)  |          1 | Không có expectation nào bắt được | GX pass; `eval_009` F1 0.80 nhưng judge chấm sai (2 điểm) | Dựng lại từ raw |
| `truncate_title` | Cắt `title` còn 6 ký tự  |          1 | Không có expectation nào về độ dài title | Tra cứu chính xác thất bại → `eval_006` MISS | Dựng lại từ raw |
| `stale_date` | Lùi `published` 365 ngày, cộng 365 vào `age_days` (≈ 40% số dòng)  |          8 | Freshness stale | `stale_ratio` 0.381 > 0.25, `is_fresh=False`; `eval_003`, `eval_007` hit nhưng trả lời sai năm (F1 0.00) | Dựng lại từ raw, tính lại `age_days` |
| `duplicate_rows` | Nhân bản dòng, trùng `paper_id`  |          2 | GX unique `paper_id` fail | GX fail (observed 4 giá trị trùng); câu categories vẫn đúng | Dựng lại từ raw (loại trùng theo `paper_id`) |

Corruption log:

- Đường dẫn: `data/results/corruption_log.json`
- Trạng thái: Có
- Nhận xét: Log có đủ 6 loại lỗi. Mỗi mục ghi `type`, `rows_affected`, danh sách `paper_ids` bị tác động và `detail` mô tả tham số (tỉ lệ 20%, 6 token rác với seed 42, cắt còn 6 ký tự, lùi 365 ngày). Cả 6 loại đều chạm ít nhất một paper trong test set.

Giải thích cách repair đảm bảo dữ liệu được phục hồi từ nguồn đáng tin cậy thay vì chỉ che kết quả lỗi:

**Repair không sửa trên dữ liệu hỏng.** `repair_from_raw(settings, run_date)` không đọc file corrupted. Nó đọc lại `data/raw/crossref_records.json` (bản raw được bảo toàn từ bước ingestion), rồi chạy lại đúng `build_clean_dataframe` như baseline. Vì vậy mọi loại lỗi (dòng bị bỏ, dòng trùng, text nhiễu, ngày lùi) đều biến mất cùng lúc, không cần vá từng lỗi riêng.

**Kết quả repair được kiểm chứng độc lập, không mặc định là đúng:**
- Dữ liệu sau repair lại đi qua quality gate và freshness (`repaired_quality_report.json` pass 6/6, `is_fresh=True`).
- Dữ liệu được index vào một collection riêng `papers-repaired`.
- Collection này được đánh giá lại bằng cùng test set.

**Idempotent:** chạy lại nhiều lần với cùng `run_date` cho ra file CSV/JSON giống hệt.

## 10. So sánh baseline, corrupted và repaired

| Metric/signal            | Baseline | Corrupted | Repaired | Thay đổi do corruption | Mức phục hồi | Nhận xét   |
| ------------------------ | -------: | --------: | -------: | -----------------------: | --------------: | ------------ |
| `retrieval_hit_rate`   |      1.000 |       0.700 |      1.000 |                      −0.300 |             100% | 3 câu MISS: 2 do `drop_latest`, 1 do `truncate_title` |
| `mean_token_f1`      |      1.000 |       0.654 |      1.000 |                      −0.346 |             100% | Giảm sâu hơn hit rate: có câu vẫn hit nhưng trả lời sai (`stale_date`, `blank_summary`) |
| `judge_accuracy`       |      1.000 |       0.500 |      1.000 |                      −0.500 |             100% | Judge khắt khe hơn F1: chấm sai cả câu có nhiễu và câu summary lấy từ bài "anh em" |
| `mean_judge_score`     |      5.000 |       3.500 |      5.000 |                      −1.500 |             100% | Câu sai năm được 2 điểm, câu summary rỗng được 1 điểm |
| Quality checks pass/fail |      6/6 pass |       4/6 pass (FAIL) |      6/6 pass |                      −2 expectations |             100% | Fail unique `paper_id` và độ dài `summary` |
| Freshness status         |      Fresh (0.042) |       Stale (0.381) |      Fresh (0.042) |                      +0.339 `stale_ratio` |             100% | Chỉ freshness bắt được `stale_date`; GX không bắt |

Nêu ít nhất hai kết luận có quan hệ nhân quả được hỗ trợ bởi artifacts:

1. **Lùi ngày làm dữ liệu stale và làm sai câu trả lời, trong khi retrieval vẫn "đúng".**
   - *Thay đổi dữ liệu:* `stale_date` lùi `published` của 8/21 dòng 365 ngày.
   - *Tín hiệu:* freshness chuyển từ `stale_ratio` 0.042 lên 0.381 và `is_fresh=False`; GX vẫn pass mọi expectation về ngày.
   - *Metric agent:* 2 câu date (`eval_003`, `eval_007`) vẫn retrieval hit nhưng trả lời `2025-06-12` thay vì `2026-06-12` (F1 0.00, judge 2/5). Đây là silent failure mà hit rate không phát hiện được.
2. **Repair từ raw làm quality và freshness phục hồi, kéo theo metric agent về đúng baseline.**
   - *Hành động:* `repair_from_raw` dựng lại 24 dòng từ `crossref_records.json`.
   - *Tín hiệu:* GX quay về pass 6/6 (hết trùng, hết `summary` rỗng); freshness về 0.042 và `is_fresh=True`.
   - *Metric agent:* hit rate, token F1 và judge accuracy về 1.000, mean judge score về 5.000, bằng baseline.

Không kết luận corruption “có tác động” nếu số liệu không cho thấy thay đổi. Nếu kết quả khác kỳ vọng, mô tả giả thuyết và cách nhóm đã kiểm tra.

**Kết quả khác kỳ vọng:** `eval_002` và `eval_006` bị retrieval MISS nhưng vẫn đạt F1 1.00, và judge chấm 5/5.
- *Giả thuyết:* corpus có 12 cặp bài gốc / "Advanced Perspectives on …" có cùng danh sách tác giả. Khi bài gốc bị drop hoặc bị cắt tiêu đề, tìm kiếm ngữ nghĩa lấy bài "anh em" và trả về đúng tác giả.
- *Cách kiểm tra:* đọc `corrupted_answers.json`. Câu trả lời của `eval_006` ("Tuan Phan, Mai Bui") trùng với tác giả của bài gốc cùng cặp (`eval_010`).
- *Kết luận:* answer metric có thể chấm "đúng" câu trả lời lấy từ sai nguồn. Vì vậy cần xét đồng thời retrieval hit.

Ngược lại, `duplicate_rows` không làm giảm metric câu categories (`eval_004`, `eval_008` vẫn F1 1.00). Tác động của lỗi này chỉ thể hiện qua GX unique.

## 11. Vấn đề tích hợp quan trọng

Mô tả một vấn đề phát sinh khi ghép các module trong pipeline và cách nhóm xử lý:

- **Triệu chứng:** Sau khi ghép pipeline và chạy thử nhiều lần:
  - 3 file manifest `data/embeddings/*.json` chứa đường dẫn tuyệt đối của máy chạy (`persist_path: "D:\\Workspace\\..."`).
  - `data/chroma/` có 5 thư mục segment dù chỉ có 3 collection.

  Nếu commit như vậy, repo sẽ lộ đường dẫn máy cá nhân (rubric trừ điểm hardcode đường dẫn tuyệt đối), `LocalEmbeddingIndex.load` sẽ hỏng trên máy người chấm, và thư mục `data/chroma` chứa segment rác.
- **Nguyên nhân:**
  - `LocalEmbeddingIndex.build` ghi `str(persist_path)`, là đường dẫn tuyệt đối resolve từ `load_settings()`.
  - Khi build lại, ChromaDB xoá collection cũ nhưng không dọn thư mục segment của nó trên đĩa.
- **Cách xử lý:**
  - `index.py` ghi `persist_path` dạng tương đối so với `project_dir` (`data/chroma`). `load()` ghép lại với `project_dir` khi đường dẫn là tương đối, và vẫn giữ tương thích với đường dẫn tuyệt đối.
  - Trước lần chạy cuối để commit, xoá các artifact chưa track trong `data/` rồi chạy lại cả hai pipeline từ đầu.
- **Cách xác minh:**
  - `persist_path` trong cả 3 manifest là `"data/chroma"`.
  - `git grep` không tìm thấy `Workspace`/`Users` trong `data/`.
  - `data/chroma` có đúng 3 thư mục segment, khớp 3 collection `papers-baseline`, `papers-corrupted`, `papers-repaired`.
  - Test `test_local_index_builds_searches_and_reloads` pass.

## 12. Giới hạn và hướng cải thiện

| Giới hạn hiện tại | Ảnh hưởng   | Hướng cải thiện có thể kiểm chứng |
| --------------------- | -------------- | ----------------------------------------- |
| Answer metric (token F1, LLM judge) không kiểm tra câu trả lời lấy từ tài liệu nào          | Chấm quá cao trạng thái corrupted: 2 câu lấy sai nguồn vẫn được tính đúng | Thêm metric *source-grounded accuracy* (đúng **và** top-1 thuộc `ground_truth_doc_ids`). Tính thử trên `corrupted_answers.json` ra 0.300, so với `judge_accuracy` 0.500                              |
| GX chưa có expectation cho độ dài `title` và nhiễu ký tự trong `summary`          | `truncate_title` và `inject_noise` lọt qua quality gate | Thêm `ExpectColumnValueLengthsToBeBetween(title, min_value=8)` và `ExpectColumnValuesToMatchRegex` cho tỉ lệ ký tự hợp lệ; kỳ vọng corrupted fail 4 expectation thay vì 2, baseline vẫn pass |
| Chạy trên snapshot 24 bài, nhiều cặp bài gần trùng nội dung          | Kết quả retrieval phụ thuộc mạnh vào exact lookup theo tiêu đề; khó tổng quát hóa | Chạy `REFRESH_SOURCE=1` với `max_results` lớn hơn, bỏ tiêu đề khỏi câu hỏi (chỉ tìm kiếm ngữ nghĩa); so sánh hit rate khi có và không có exact lookup                              |
| LLM judge có tính ngẫu nhiên nhẹ (phần giải thích khác nhau giữa các lần chạy)          | Chưa đảm bảo điểm judge ổn định tuyệt đối khi đổi model | Cố định `temperature=0` (đã làm) và thêm seed hoặc cache kết quả judge theo (câu hỏi, câu trả lời); kiểm chứng bằng việc chạy lại 3 lần cho `judge_accuracy` giống nhau                              |

## 13. Checklist trước khi nộp

- [x] Thông tin nhóm và repository chính xác.
- [x] Phân công khớp với module, artifact và kết quả thực tế.
- [x] Lệnh tái hiện đã được chạy lại trên phiên bản dùng để nộp.
- [x] Baseline, corrupted và repaired dùng cùng evaluation set.
- [x] Bảng metrics khớp với các file trong `data/results/`.
- [x] Quality/freshness conclusions khớp với `data/quality/`.
- [x] Các đường dẫn báo cáo và artifact truy cập được.
- [x] Mỗi thành viên đã hoàn thành báo cáo vai trò riêng.
- [x] Không có `.env`, API key, token hoặc secret trong source, report, log hay ảnh.
