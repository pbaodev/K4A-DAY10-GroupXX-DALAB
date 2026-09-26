# Member Role Report — Day 10: Data Pipeline & Data Observability

## 1. Thông tin cá nhân

| Thông tin         | Nội dung                  |
| ------------------ | -------------------------- |
| Họ và tên       | Trang Phước Hoàng Minh |
| MSSV               | 2A202602690 |
| Khóa/Lớp         | K4 |
| Tên nhóm         | DALAB |
| Vai trò chính    | M2 — Data Foundation & Recovery (@hminh1231, issue #3) |
| Repository         | https://github.com/pbaodev/K4A-DAY10-GroupXX-DALAB |
| Ngày hoàn thành | 2026-09-26 |

## 2. Vai trò và phạm vi công việc

### Phần việc sở hữu

| Module/deliverable | File/hàm phụ trách | Input nhận vào | Output bàn giao  | Trạng thái |
| ------------------ | --------------------- | ---------------- | ----------------- | ------------ |
| CP0 — Raw ingestion | `src/ingestion/crossref.py` · `fetch_source_records`, `parse_crossref_payload`, `load_raw_records` | Crossref `/works` hoặc snapshot `data/raw/crossref_response.json` | `PaperRecord` list; khi refresh thì thêm `data/raw/crossref_records.json` | Hoàn thành |
| CP1 — Cleaning | `src/ingestion/cleaning.py` · `build_clean_dataframe`, `compose_text_for_embedding` | `list[PaperRecord]`, `run_date` | Dataframe đúng contract: `paper_id`, ngày `YYYY-MM-DD`, `age_days`, `text_for_embedding` | Hoàn thành |
| CP5 — Idempotent repair | `src/ingestion/repair.py` · `repair_from_raw` | `Settings`, cùng `run_date` của lần chạy, raw records | `data/clean/papers_clean_repaired.csv`, `papers_clean_repaired.json` | Hoàn thành |

Clean dataframe là đầu vào của M3 (test set, index, corruption) và của M4 (quality gate đọc `paper_id`, `summary`, `age_days`). M1 gọi `repair_from_raw` trong `corruption_flow.py` sau khi đo dữ liệu bẩn.

### Việc hỗ trợ ngoài phạm vi chính

| Hoạt động | Thành viên/module được hỗ trợ | Kết quả |
| --- | --- | --- |
| Giữ `published`/`updated` là chuỗi ngày, không để Timestamp hoặc `None` | M3 — Chroma metadata | Index baseline trên main có 24 document. Contract clean không đẩy list/Timestamp vào metadata. |
| Export `compose_text_for_embedding` để corruption ghép lại text sau khi sửa summary/title | M3 — `corruption.py` | `text_for_embedding` vẫn là 5 dòng Title / Authors / Published / Categories / Summary sau khi dữ liệu bị sửa. |

## 3. Kết quả theo vai trò

| Nhiệm vụ đã thực hiện | File/hàm/artifact liên quan | Kết quả bàn giao | Cách xác minh |
| --- | --- | --- | --- |
| Parse Crossref, fallback snapshot, không ghi đè raw khi API lỗi | `src/ingestion/crossref.py` | Snapshot trong repo ra 24 `PaperRecord` | `tests/test_ingestion.py`: offline không rewrite raw; HTTP 429 fallback snapshot; payload live rỗng thì đọc lại snapshot |
| Chuẩn hóa schema, `age_days`, embedding text, sort ổn định | `src/ingestion/cleaning.py` | Phase 1: `raw_records=24`, `clean_rows=24` | `data/reports/phase1_report.md`; GX baseline `observed_value=24`, success `true` |
| Repair từ raw, bỏ qua file clean đã bị sửa | `src/ingestion/repair.py` | Repaired 24 dòng, metric và freshness trở về baseline | `data/results/repaired_metrics.json`, `data/quality/freshness_report_repaired.json`; test so hash CSV/JSON của hai lần repair |

Cùng `run_date`, `repair_from_raw` không đọc dataframe corrupted. Trên artifact main, repaired khớp baseline (`retrieval_hit_rate` 1.0, `mean_token_f1` 1.0, `judge_accuracy` 1.0, `mean_judge_score` 5, `is_fresh` true, `stale_ratio` 0.0417, 24 dòng). Corrupted thì không khớp: 21 dòng, hit rate 0.7, token F1 0.654, judge accuracy 0.5, `is_fresh` false.

## 4. Giải thích phần kỹ thuật đã thực hiện

### Vấn đề cần giải quyết

Pipeline phía sau cần một bản ghi sạch, ổn định, và một cách dựng lại đúng bản đó sau khi ai đó làm hỏng dữ liệu. Nếu cleaning đổi kiểu ngày hoặc thứ tự dòng mỗi lần chạy, test set và index sẽ lệch. Nếu repair vá trên dataframe đã bị tiêm lỗi, một kiểu lỗi mới sẽ sót.

### Cách triển khai

**Ingestion.** `parse_crossref_payload` chỉ nhận `message.items`. DOI cắt prefix `https://doi.org/` và `dx.doi.org`. Abstract unescape HTML rồi xóa thẻ. Ngày lấy từ `date-parts`, thiếu tháng/ngày thì điền `01`. Record thiếu DOI, title hoặc abstract bị bỏ; DOI trùng bị bỏ. `fetch_source_records` mặc định chỉ đọc snapshot và không ghi raw. Khi `REFRESH_SOURCE=1`, gọi API tối đa 3 lần, chờ tăng dần nếu gặp 429, 503 hoặc lỗi mạng. API hỏng thì đọc snapshot cũ, không thay file snapshot bằng response lỗi.

**Cleaning.** Bỏ dòng thiếu `paper_id`, title hoặc ngày publish. `age_days` tính một lần từ `run_date` truyền vào, không lấy `datetime.now()` bên trong vòng lặp. `published` và `updated` ghi `YYYY-MM-DD`. Deduplicate `paper_id` giữ bản đầu, rồi sort `published` giảm dần, `paper_id` tăng dần, `kind="stable"`, `reset_index`. `compose_text_for_embedding` là hàm riêng để corruption dựng lại đúng 5 dòng sau khi sửa từng trường.

**Repair.** `repair_from_raw` gọi `load_raw_records` rồi `build_clean_dataframe` với đúng `run_date` của lần chạy. Ghi CSV và JSON repaired. File clean corrupted không nằm trên đường đi này.

### Input, output và contract

| Thành phần | Mô tả |
| --- | --- |
| Input | Payload Crossref hoặc `data/raw/crossref_response.json`; sau đó `data/raw/crossref_records.json` và một `run_date` |
| Output | `PaperRecord`; clean dataframe 16 cột theo contract #1; repaired CSV/JSON |
| Module phụ thuộc | `core.config.Settings`, `core.utils` |
| Module sử dụng output | `evaluation/testset.py`, `retrieval/index.py`, `ingestion/corruption.py`, `observability/quality.py`, `pipelines/phase1.py`, `pipelines/corruption_flow.py` |
| Điều kiện lỗi cần xử lý | API 429/503, payload không có `items`, snapshot mất, record thiếu khóa, repair khi chưa có raw records (`FileNotFoundError`) |

### Cách xác minh

```bash
python -c "from core.config import load_settings; from ingestion.crossref import fetch_source_records; s=load_settings(); r=fetch_source_records(s); print(len(r))"
```

- **Kết quả mong đợi:** 24 record từ snapshot khi không bật `REFRESH_SOURCE`.
- **Kết quả thực tế:** `phase1_report.md` trên main ghi `mode=snapshot`, `raw_records=24`, `clean_rows=24`, `run_date=2026-09-25T10:39:36+00:00`. GX baseline success `true`, observed row count 24.
- **Artifact/log:** `data/raw/crossref_records.json`, `data/clean/papers_clean.json`, `data/clean/papers_clean_repaired.json`. Test của phần này nằm ở `tests/test_ingestion.py`.

## 5. Một quyết định kỹ thuật quan trọng

- **Bối cảnh:** Repair có thể sửa từng ô hỏng trên dataframe corrupted, hoặc bỏ dataframe đó và làm sạch lại từ raw.
- **Các phương án đã cân nhắc:** Vá theo `corruption_log` (nhanh, nhưng phải biết hết mọi kiểu lỗi). Dựng lại từ `crossref_records.json` bằng cùng hàm cleaning (không phụ thuộc danh sách lỗi).
- **Phương án đã chọn:** `repair_from_raw` chỉ đọc raw records.
- **Lý do:** Log hiện có 6 kiểu lỗi. Nếu lần sau thêm kiểu mới mà repair vẫn vá theo danh sách cũ, dữ liệu bẩn sẽ lọt vào index. Raw snapshot không bị corruption đụng tới, nên làm sạch lại cho cùng một `run_date` ra cùng bảng.
- **Bằng chứng quyết định phù hợp:** Test `test_repair_from_raw_is_idempotent_and_ignores_clean_edits` ghi file clean giả `[{"paper_id": "corrupted"}]`. Repair không chứa `paper_id` đó. Hai lần gọi cùng `run_date` có cùng hash CSV và JSON. Trên main, repaired metrics trùng baseline và freshness repaired trùng freshness baseline (`stale_rows` 1, `total_rows` 24).

## 6. Một lỗi hoặc blocker đã xử lý

- **Triệu chứng/lỗi nguyên văn:** Test repair ghi `papers_clean_repaired.csv/json` vào `data/clean/` của repo, không vào thư mục tạm của pytest.
- **Lệnh hoặc bước tái hiện:** Chạy `tests/test_ingestion.py` khi `settings.paths` vẫn trỏ path mặc định của project.
- **Nguyên nhân gốc:** `repair_from_raw` ghi đúng path trong `Settings`. Fixture test đổi vài path sang `tmp_path` nhưng lúc đầu chưa đổi `repaired_clean_csv` và `repaired_clean_json`.
- **Cách xử lý:** Fixture `settings` trong `tests/conftest.py` trỏ hai path repaired vào `tmp_path / "data" / "clean"`.
- **Cách xác minh sau khi sửa:** `test_repair_from_raw_is_idempotent_and_ignores_clean_edits` so hash hai lần ghi và kiểm tra chuỗi `corrupted` không có trong JSON repaired.
- **Điều học được:** Hàm ghi artifact phải nhận path từ settings. Test muốn cô lập thì phải đổi đủ mọi path mà hàm đó ghi, không chỉ path của bước đang đọc.

## 7. Hiểu biết về luồng end-to-end

Giải thích ngắn gọn bằng lời của bạn:

1. Dữ liệu đi từ Crossref đến vector index như thế nào?
2. Evaluation set và ground-truth document IDs dùng để đo retrieval/answer quality ra sao?
3. Quality checks khác freshness monitoring ở điểm nào trong bài lab?
4. Vì sao phải dùng cùng test set cho baseline, corrupted và repaired?
5. Repair được xem là thành công dựa trên artifact và metric nào?

**Câu trả lời:**

1. Crossref payload (API hoặc snapshot) thành `PaperRecord`, lưu raw records. Cleaning tạo dataframe và `text_for_embedding`. Index nhúng đoạn text đó vào collection Chroma riêng cho từng trạng thái.
2. Test set lấy câu hỏi từ clean dataframe. `ground_truth_doc_ids` là `paper_id` (DOI). Hit rate đúng khi ID retrieval nằm trong danh sách đó. Token F1 so câu trả lời với `ground_truth` sinh từ summary, authors, published hoặc categories của cùng dòng.
3. Quality check nhìn schema lúc ghi: null, trùng `paper_id`, độ dài summary, số dòng. Freshness nhìn tuổi dữ liệu: `age_days > 180`, `is_fresh` khi `stale_ratio <= 0.25`. Một bảng có thể qua quality gate mà vẫn stale, hoặc ngược lại.
4. Ba trạng thái phải dùng cùng `data/eval/test_set.json`. Đổi bộ đề thì không biết metric giảm vì dữ liệu hỏng hay vì câu hỏi khác.
5. Repair thành công khi dataframe dựng lại từ raw khớp cleaning của cùng `run_date`, quality gate repaired success `true`, freshness về `is_fresh=true`, và bốn metric chính trở lại bằng baseline. Trên main cả bốn điều này đều đúng.

## 8. Phân tích kết quả

Số liệu lấy từ artifact trên `main`: `baseline_metrics.json`, `corrupted_metrics.json`, `repaired_metrics.json`, ba file freshness và `corruption_report.md`. Ragas không chạy (`skipped`).

### Metrics chính

| Metric/signal | Baseline | Corrupted | Repaired | Nhận xét của cá nhân |
| --- | ---: | ---: | ---: | --- |
| `retrieval_hit_rate` | 1.0 | 0.7 | 1.0 | Mất 0.3 vì drop/truncate/duplicate đụng paper trong test set. Repair trả về 1.0. |
| `mean_token_f1` | 1.0 | 0.654 | 1.0 | Giảm ít hơn judge accuracy. Câu authors vẫn F1 1.0 dù hit rate của loại đó chỉ 0.333. |
| `judge_accuracy` | 1.0 | 0.5 | 1.0 | Mức giảm lớn nhất trong các tỷ lệ 0–1 (Δ −0.5). |
| `mean_judge_score` | 5 | 3.5 | 5 | Giảm 1.5 điểm trên thang 1–5. Không so trực tiếp với các tỷ lệ 0–1. |
| Quality checks | pass | fail | pass | Corrupted fail unique `paper_id` và độ dài `summary`. Row count 21 vẫn pass vì còn trong khoảng 5–5000. |
| Freshness status | fresh (0.0417) | stale (0.381) | fresh (0.0417) | `stale_date` đẩy 8/21 dòng quá 180 ngày. Repair về 1/24. |

### Kết luận từ số liệu

Hoàn thành hai chuỗi nguyên nhân–bằng chứng sau:

1. `stale_date` lùi `published` 365 ngày và tăng `age_days` → freshness corrupted `is_fresh=false`, `stale_ratio` 0.381 → câu hỏi `date` vẫn hit rate 1.0 nhưng `mean_token_f1` 0.0, vì retrieval còn thấy bài còn ngày trong index đã khác ground truth.
2. `repair_from_raw` đọc lại raw records, không đọc file corrupted → quality repaired pass, freshness `is_fresh=true`, và cả bốn metric chính bằng baseline. Breakdown `summary` / `authors` / `date` / `categories` đều về hit rate 1.0 và token F1 1.0.

Corruption ảnh hưởng rõ nhất lên phần mình sở hữu là `stale_date`: nó sửa đúng hai cột cleaning tạo ra (`published`, `age_days`) và làm câu date trả lời sai dù document vẫn được tìm thấy. `blank_summary` thì làm GX fail độ dài summary và kéo F1 của nhóm summary từ 1.0 xuống 0.514.

Nhóm `authors` trên corrupted có hit rate 0.333 nhưng token F1 vẫn 1.0. Mình tưởng retrieval miss thì câu trả lời cũng sai. Bảng breakdown cho thấy text đáp án vẫn khớp trong khi document ID thì không. Hit rate và token F1 không thay thế cho nhau. Nhóm `categories` giữ 1.0 / 1.0 vì sáu kiểu lỗi không xóa `categories_joined`.

## 9. Điều học được và hướng cải thiện

### Ba điều quan trọng nhất

1. Raw snapshot là bản để chạy lại, không phải bản để sửa. Cleaning và repair phải dùng chung một hàm thì repaired mới bằng baseline.
2. Quality gate không thay freshness. Bảng 21 dòng vẫn qua expectation số dòng, trong khi `stale_ratio` đã vượt 0.25.
3. Hỏng `published` trong clean schema không làm retrieval date fail, nhưng làm câu trả lời date sai. Đó là silent failure ở tầng answer, không phải ở tầng hit.

### Nếu có thêm thời gian

Thêm một check cho `published` lệch hơn 365 ngày so với raw record cùng `paper_id`. Đo bằng số dòng mà `published` repaired khác `published` corrupted, và bằng token F1 của riêng `question_type=date` trước và sau repair. Hiện F1 date đã cho thấy hướng này: 0.0 khi corrupted, 1.0 khi repaired.

## 10. Cam kết của thành viên

Đánh dấu sau khi tự kiểm tra:

- [x] Nội dung báo cáo phản ánh đúng phần việc và mức hiểu của tôi.
- [x] Tôi có thể giải thích luồng end-to-end, không chỉ module mình phụ trách.
- [x] Mọi kết luận về kết quả đều có artifact hoặc metric để đối chiếu.
- [x] Tôi không ghi “đã chạy thành công” cho phần chưa được kiểm chứng.
- [x] Báo cáo không chứa `.env`, API key, token hoặc secret.
- [x] Báo cáo này không phải bản sao nguyên văn của báo cáo nhóm hoặc báo cáo thành viên khác.

**Họ và tên:** Trang Phước Hoàng Minh
**Ngày xác nhận:** 2026-09-26
