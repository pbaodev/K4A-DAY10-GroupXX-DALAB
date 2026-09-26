# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `DALAB`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `K4-L3-DAY10-GroupXX-DALAB`

---

## # Thành viên

| STT | Họ và tên | MSSV | Email | GitHub | Vai trò & Phân công công việc | Issue | Báo cáo cá nhân |
|---:|---|---|---|---|---|---|---|
| 1 | Phan Duy Bảo | 2A202602767 | [Email] | @pbaodev | Trưởng nhóm / Pipeline Integrator (`pipelines/phase1.py`, `pipelines/corruption_flow.py`, `core/`, artifacts `data/`) | #9 | `report/<MSSV1>_HoTen.md` |
| 2 | Trang Phước Hoàng Minh | 2A202602690 | hminh1231@gmail.com | @hminh1231 | Data Foundation & Recovery (`crossref.py`, `cleaning.py`, `repair.py`) | #3 | `report/2A202602690_TrangPhuocHoangMinh.md` |
| 3 | Vũ Quốc Bảo | 2A202602829 | baovq2509@gmail.com | @byllkoy259 | RAG & Evaluation (`testset.py`, `corruption.py`, `retrieval/`, ChromaDB) | #6 | `report/2A202602829_VuQuocBao.md` |
| 4 | Lê Gia Bảo | 2A202602887 | [Email] | @oabga | Observability & Reporting (`quality.py` GX 1.x, Freshness SLA, `reporting.py`) | #5 | `report/2A202602887_LeGiaBao.md` |

*(Nếu nhóm có 3 hoặc 5-6 thành viên, xem bảng phân công chi tiết theo vai trò trong file `CHECKPOINTS.md`)*.

---

## # Cá nhân

### ## HoVaTen1-MSSV1
- **Vai trò:** Trưởng nhóm & Điều phối Pipeline.
- **Công việc chi tiết đã hoàn thành:**
  - Thiết lập cấu hình hệ thống `core/config.py` và đường dẫn artifacts `core/utils.py`.
  - Kết nối luồng thực thi trong `src/pipelines/phase1.py` và `src/pipelines/corruption_flow.py`.
  - Kiểm tra tính nhất quán của các artifacts và theo dõi Contributor tracking trên GitHub nhánh `main`.
- **Điều học được / Đóng góp chính:**
  - Hiểu sâu sắc về thiết kế Idempotent Pipeline và quản lý trạng thái luồng dữ liệu đa tầng.

### ## TrangPhuocHoangMinh-2A202602690
- **Vai trò:** M2 — Data Foundation & Recovery (@hminh1231, issue #3): Crossref ingestion, cleaning, idempotent repair.
- **Công việc chi tiết đã hoàn thành:**
  - **CP0 — Raw ingestion** (`src/ingestion/crossref.py`):
    - `parse_crossref_payload` bóc `message.items` thành `PaperRecord`: DOI bỏ prefix `doi.org`, title, abstract đã gỡ markup, authors, subject, ngày `YYYY-MM-DD`.
    - Mặc định đọc snapshot `data/raw/crossref_response.json`, không ghi đè raw. `REFRESH_SOURCE=1` gọi API, retry 3 lần khi 429/503 hoặc lỗi mạng, và fallback về snapshot nếu API hỏng.
    - Snapshot trong repo parse ra 24 record.
  - **CP1 — Cleaning** (`src/ingestion/cleaning.py`):
    - Bỏ record thiếu `paper_id`, title hoặc ngày; khử trùng `paper_id`; sort `published` giảm dần rồi `paper_id`.
    - `published`/`updated` là chuỗi `YYYY-MM-DD` (không dùng Timestamp). `age_days = (run_date - published).days`.
    - `compose_text_for_embedding` ghép 5 dòng Title / Authors / Published / Categories / Summary.
    - Phase 1 trên main: 24 raw record → 24 dòng sạch (`data/clean/papers_clean.json`).
  - **CP5 — Repair** (`src/ingestion/repair.py`):
    - `repair_from_raw` chỉ đọc `crossref_records.json`, chạy lại `build_clean_dataframe` với cùng `run_date`, ghi `papers_clean_repaired.csv/json`. Không đọc file corrupted.
    - Cùng `run_date` thì hai lần repair ra cùng byte. Artifact repaired trên main khớp baseline: 24 dòng, hit rate 1.0, token F1 1.0, freshness `is_fresh=true`.
  - Báo cáo cá nhân: `report/2A202602690_TrangPhuocHoangMinh.md`.
- **Điều học được / Đóng góp chính:**
  - Raw snapshot phải được giữ nguyên để repair dựng lại dữ liệu sạch, thay vì sửa từng ô trên dataframe đã bị tiêm lỗi.
  - `published` và `age_days` trên clean schema là chỗ `stale_date` làm freshness và câu hỏi date gãy, rồi repair kéo cả hai trở lại.

### ## VuQuocBao-2A202602829
- **Vai trò:** M3 — RAG & Evaluation (@byllkoy259, issue #6): test set benchmark, corruption suite, retrieval & agent.
- **Công việc chi tiết đã hoàn thành:**
  - **CP2 — Test set** (`src/evaluation/testset.py`):
    - `build_test_set` sinh 10 câu hỏi `eval_001`–`eval_010`, phủ 4 loại (3 summary / 3 authors / 2 date / 2 categories).
    - Chọn paper deterministic: sort theo ngày giảm dần, lấy cách đều và luôn gồm bài mới nhất.
    - Câu hỏi và `ground_truth` khớp cách `retrieval/qa.py` trích câu trả lời.
    - Kết quả: baseline hit rate 1.000, token F1 1.000.
  - **CP2 — Retrieval & agent** (`src/retrieval/`):
    - Kiểm chứng collection `papers-baseline` đủ 24 docs và metadata không có kiểu ChromaDB từ chối.
    - Thêm `run_agent_demo`: chạy agent trên vài câu hỏi, ghi lý do `skipped` thay vì làm dừng pipeline. Thử router `mock` và `openai/gpt-4o-mini` (3/3 `ok`).
    - Manifest embedding lưu đường dẫn Chroma dạng tương đối (`data/chroma`), không lộ đường dẫn máy cá nhân.
  - **CP4 — Corruption suite** (`src/ingestion/corruption.py`):
    - `corrupt_clean_dataframe` tiêm 6 loại lỗi deterministic (seed 42): `drop_latest`, `blank_summary`, `inject_noise`, `truncate_title`, `stale_date`, `duplicate_rows`.
    - Nhắm đúng vào paper trong test set qua hàm dùng chung `plan_eval_items`; ghi `corruption_log.json`.
    - Kết quả trên dữ liệu corrupted: hit rate 1.000 → 0.700, token F1 1.000 → 0.654, `judge_accuracy` 1.000 → 0.500; quality gate GX FAIL, freshness `is_fresh=False` (`stale_ratio` 0.381).
  - Báo cáo cá nhân: `report/2A202602829_VuQuocBao.md`.
- **Điều học được / Đóng góp chính:**
  - Muốn đo được silent failure thì bộ đề phải cố định và sinh từ dữ liệu sạch, còn lỗi phải tiêm có chủ đích vào đúng các paper được hỏi.
  - Agent có thể trả lời "đúng" từ sai tài liệu (lấy nhầm bài "Advanced Perspectives" có cùng tác giả). Vì vậy cần đo cả retrieval hit lẫn chất lượng câu trả lời.

### ## LeGiaBao-2A202602887
- **Vai trò:** M4 — Data Observability & Reporting (@oabga, issue #5): Great Expectations 1.x, Freshness SLA, báo cáo so sánh 3 trạng thái.
- **Công việc chi tiết đã hoàn thành:**
  - Thiết lập Quality Gate theo chuẩn mới **Great Expectations 1.x** trong `src/observability/quality.py` với `gx.get_context()`, `add_pandas()` và các expectation cần thiết để kiểm tra schema, độ duy nhất, độ dài và tính hợp lệ của dữ liệu trước khi index.
  - Tính toán và ghi báo cáo Freshness SLA để theo dõi tỷ lệ bài báo quá hạn `age_days > 180`; báo cáo này quyết định `is_fresh` và cảnh báo sớm khi dữ liệu không còn đủ tươi cho serving layer.
  - Hỗ trợ chuẩn hóa các biểu đồ/metric trong `src/observability/reporting.py` và xuất bảng đối chiếu Baseline vs Corrupted vs Repaired vào `data/reports/corruption_report.md`, đồng thời lưu các artifact `data/quality/*.json` và `data/quality/freshness_report*.json`.
  - Kiểm tra các dấu hiệu của Silent Failure: dữ liệu có thể còn `pass` GX nhưng vẫn trả lời sai do stale_date hoặc summary rỗng, nên cần báo động ở tầng observability trước khi agent đưa ra trả lời.
- **Điều học được / Đóng góp chính:**
  - Hệ thống cảnh báo sớm phải đo lường cả chất lượng dữ liệu và độ tươi của dữ liệu, không chỉ độ khớp kiểu dữ liệu. Với `stale_date`, retrieval vẫn hit nhưng câu trả lời sai vì `published` đã bị lùi, nên chỉ có Freshness SLA hoặc answer-level metric mới chặn được lỗi đúng lúc.
  - Đây là cách thiết lập một Quality Gate hiệu quả: dữ liệu bị lỗi phải bị chặn ở ingress, không được để lọt vào serving layer mà chỉ “vẫn chạy” và tạo ra Silent Failure khó phát hiện.
