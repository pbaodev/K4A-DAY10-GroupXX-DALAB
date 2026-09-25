# Danh Sách Thành Viên & Báo Cáo Phân Công Nhóm

- **Tên Nhóm:** `DALAB`
- **Mã Nhóm / Lớp:** `K4-L3-DAY10`
- **Tên Repository Nộp Bài:** `K4-L3-DAY10-GroupXX-DALAB`

---

## # Thành viên

| STT | Họ và tên | MSSV | Email | GitHub | Vai trò & Phân công công việc | Issue | Báo cáo cá nhân |
|---:|---|---|---|---|---|---|---|
| 1 | Phan Duy Bảo | 2A202602767 | [Email] | @pbaodev | Trưởng nhóm / Pipeline Integrator (`pipelines/phase1.py`, `pipelines/corruption_flow.py`, `core/`, artifacts `data/`) | #9 | `report/<MSSV1>_HoTen.md` |
| 2 | Trang Phước Hoàng Minh | 2A202602690 | [Email] | @hminh1231 | Data Foundation & Recovery (`crossref.py`, `cleaning.py`, `repair.py`) | #3 | `report/<MSSV2>_HoTen.md` |
| 3 | Vũ Quốc Bảo | 2A202602829 | baovq2509@gmail.com | @byllkoy259 | RAG & Evaluation (`testset.py`, `corruption.py`, `retrieval/`, ChromaDB) | #6 | `report/2A202602829_VuQuocBao.md` |
| 4 | Lê Gia Bảo | 2A202602887 | [Email] | @oabga | Observability & Reporting (`quality.py` GX 1.x, Freshness SLA, `reporting.py`) | #5 | `report/<MSSV4>_HoTen.md` |

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

### ## HoVaTen2-MSSV2
- **Vai trò:** Phụ trách Ingestion, Làm sạch & Phục hồi dữ liệu.
- **Công việc chi tiết đã hoàn thành:**
  - Xây dựng module thu thập Crossref API với cơ chế Fallback offline trong `src/ingestion/crossref.py`.
  - Chuẩn hóa schema, tính toán trường `age_days` và `text_for_embedding` trong `src/ingestion/cleaning.py`.
  - Thực thi cơ chế Idempotent Repair phục hồi dữ liệu từ raw snapshot.
- **Điều học được / Đóng góp chính:**
  - Kỹ thuật truy vết nguồn gốc dữ liệu (Data Lineage) và bảo toàn raw snapshot trước khi biến đổi.

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

### ## HoVaTen4-MSSV4
- **Vai trò:** Phụ trách Data Observability & Benchmark Evaluation.
- **Công việc chi tiết đã hoàn thành:**
  - Thiết lập Quality Gate theo chuẩn mới **Great Expectations 1.x** và giám sát Freshness SLA trong `src/observability/quality.py`.
  - Xây dựng bộ câu hỏi đánh giá chuẩn trong `src/evaluation/testset.py`.
  - Đo lường và xuất bảng đối chiếu 3 trạng thái vào `data/reports/corruption_report.md`.
- **Điều học được / Đóng góp chính:**
  - Cách thiết lập hệ thống cảnh báo sớm chặn đứng hiện tượng Silent Failure trước khi dữ liệu vào serving layer.
