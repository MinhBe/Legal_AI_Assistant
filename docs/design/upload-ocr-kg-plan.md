# Kế hoạch nâng cấp: tải tài liệu lên → OCR → bổ sung Knowledge Graph

Ngày 16/11/2026. Căn cứ: thiết kế `docs/design/LawVN-v1.1.md`, hàng đợi `docs/design/v1.1-gap.md`, code tại `e42d592`.
Mục tiêu: bản chạy được để Minh tester ngày mai, phần đánh bóng làm sau. Không cần LLM ở bất kỳ bước nào (chi phí chạy $0).

## 1. So sánh hiện trạng và mục tiêu

| Mảng | Hiện có (đã kiểm) | Thiết kế v1.1 yêu cầu | Bản nâng cấp này làm |
|---|---|---|---|
| Tải tài liệu lên | Chưa có endpoint nào, chưa có `python-multipart` | §8: hồ sơ của khách là mức A, ở lại nội bộ | `POST /api/uploads` nhận PDF, ảnh (png, jpg, tiff), DOCX, TXT; tối đa 20 MB |
| OCR | Chưa có (container không có tesseract, PyMuPDF, Pillow) | §7B.3: ASR/OCR phải tự host | pypdfium2 lấy lớp chữ PDF; trang nào không có chữ thì render ra ảnh rồi tesseract `vie+eng`; DOCX dùng python-docx; tất cả chạy trong container |
| Tách cấu trúc | `ingestion/parser.py` tách Điều/Khoản/Điểm cho văn bản luật; chỉ chạy bằng CLI | §6: nạp có nguồn, hash, luật sư duyệt | Nếu nhận ra cấu trúc Điều thì dùng parser có sẵn; nếu không (hợp đồng, công văn) thì chia đoạn thành node `section` |
| Knowledge Graph | `graph/builder.py` lấy hạt từ `search_nodes` trên mọi `legal_node`; cạnh lấy từ `node_reference`, `node_supersession`, `document_relation` | §5.1: đồ thị quan hệ văn bản | Node của file tải lên ghi vào `legal_node` cùng embedding; `extract_refs` nối sang điều luật được dẫn chiếu ("khoản 2 Điều 35 BLLĐ"). Graph tự hiện, có thêm bộ lọc "tài liệu tải lên" |
| An toàn dữ liệu | Không phân mức | §4: mức A không ra ngoài, không làm căn cứ khi chưa duyệt | Mọi file tải lên mang `data_class=A`, `status=pending_review`; mặc định bị loại khỏi truy xuất trả lời chat; không gọi LLM ngoài |
| Duyệt | Dashboard duyệt câu hỏi ngoài kho | §9, §6: luật sư duyệt trước khi vào nhánh chính | Trang tải lên có nút "Duyệt" / "Loại"; đã duyệt thì mới được bật cho truy xuất (cờ riêng) |

## 2. Thiết kế kỹ thuật

**Luồng:** tải lên → lưu file vào `data/uploads/<sha256>.<ext>` (trùng hash thì trả bản đã có) → trích chữ (lớp chữ, OCR theo từng trang) → chuẩn hoá NFC → tách cấu trúc → ghi `legal_document` và `legal_node` kèm embedding → trích dẫn chiếu, ghi `node_reference` → trả về báo cáo.

**Dữ liệu:**
- Bảng mới `uploaded_file`: `upload_id`, `doc_id`, `filename`, `mime`, `sha256`, `size_bytes`, `pages`, `ocr_pages`, `chars`, `mean_ocr_conf`, `parse_mode` (`articles` hoặc `sections`), `n_nodes`, `n_refs`, `data_class`, `status`, `error`, `created_at`. Tạo bằng `CREATE TABLE IF NOT EXISTS` trên Postgres compose cục bộ. Hoàn tác: `DROP TABLE uploaded_file` và xoá các `legal_document` có `doc_type='upload'`.
- `legal_document`: `doc_id = up_<8 ký tự hash>`, `doc_type='upload'`, `status='pending_review'`, `source_url='upload://<filename>'`.
- `legal_node`: node `article`/`clause`/`point` như luật, hoặc `section` cho văn bản tự do (mỗi đoạn khoảng 800 ký tự, cắt theo đoạn văn).

**API:**
- `POST /api/uploads`: multipart `file`, tuỳ chọn `title`. Trả về báo cáo (số trang, số trang OCR, độ tin cậy OCR, số node, số dẫn chiếu, `doc_id`).
- `GET /api/uploads`: danh sách file đã tải lên.
- `GET /api/uploads/{id}`: chi tiết, kèm xem trước chữ.
- `PATCH /api/uploads/{id}`: đổi trạng thái `approved` / `rejected`.
- `DELETE /api/uploads/{id}`: xoá file, node và cạnh liên quan.
- `GET /api/graph?doc_id=up_xxx`: graph quanh một tài liệu tải lên (hạt là các node của chính tài liệu đó).

**Truy xuất:** `search_nodes` mặc định loại `doc_type='upload'`, trừ khi file đã `approved` và gọi với `include_uploads=True`. Graph thì luôn hiện được (chỉ xem, không làm căn cứ).

**Frontend:**
- Trang mới `/upload`: kéo thả file, thanh tiến trình, bảng kết quả, nút "Xem trên graph", nút Duyệt / Loại / Xoá.
- Trang graph: nhận `?doc_id=`, tô màu riêng cho node tải lên. Không thêm gói npm.

**Thư viện (cần build lại image api):**
- pip: `python-multipart`, `pypdfium2`, `pillow`.
- apt: `tesseract-ocr`, `tesseract-ocr-vie`.

## 3. Các bước (mỗi bước một commit, có test)

| # | Việc | File | Test |
|---|---|---|---|
| U1 | Thư viện + Dockerfile, build lại api | `backend/requirements.txt`, `backend/Dockerfile` | `tesseract --list-langs` có `vie`; import pypdfium2 |
| U2 | Trích chữ: txt, docx, pdf có chữ, pdf scan, ảnh | `backend/app/upload/extract.py` | `tests/test_upload_extract.py`, fixture sinh tại chỗ (ảnh chữ tiếng Việt có dấu, PDF 2 trang) |
| U3 | Tách cấu trúc: dùng parser luật, nếu không được thì chia đoạn; ghi node, embedding, dẫn chiếu | `backend/app/upload/ingest.py` (gọi lại `ingestion/ingest.py`, `ingestion/references.py`) | `tests/test_upload_ingest.py` (chạy trên DB, đánh dấu `db`) |
| U4 | Bảng `uploaded_file` + 5 endpoint | `backend/app/db/models.py`, `db/init/002_uploads.sql`, `backend/app/api/routes.py` | `tests/test_upload_api.py` (TestClient) |
| U5 | Truy xuất loại file chưa duyệt; graph theo `doc_id` | `backend/app/rag/search.py`, `backend/app/graph/builder.py` | Test: chat không trích file pending; graph có cạnh dẫn chiếu |
| U6 | Trang `/upload` + liên kết từ graph và menu | `frontend/app/upload/page.tsx`, `frontend/app/graph/page.tsx` | Mở trình duyệt, tải file mẫu, xem graph |
| U7 | Tài liệu tester + file mẫu | `docs/tester-upload.md`, `data/samples/` | Chạy lại toàn bộ pytest |

## 4. Kịch bản cho tester (ngày mai)
1. Mở `http://localhost:3000/upload`, tải lên 3 file mẫu: `data/samples/hop-dong-mau.docx`, `data/samples/quyet-dinh-scan.png` (ảnh chụp, phải OCR), `data/samples/noi-quy.pdf`.
2. Kiểm tra: mỗi file có số trang, số trang OCR, độ tin cậy OCR, số node, số dẫn chiếu tới BLLĐ.
3. Bấm "Xem trên graph": thấy node của tài liệu, có cạnh tới Điều luật được nhắc (ví dụ Điều 35 BLLĐ 2019).
4. Hỏi chat một câu liên quan: câu trả lời **không** được trích từ file chưa duyệt. Duyệt file rồi thử lại với chế độ bật tài liệu tải lên.
5. Xoá file: node và cạnh biến mất khỏi graph.

## 5. Rủi ro và giới hạn của bản đầu
- OCR tiếng Việt bằng tesseract có thể sai dấu trên ảnh mờ. Độ tin cậy OCR hiển thị từng trang để thấy ngay.
- Tách Điều/Khoản cho văn bản scan dễ lệch; khi độ phủ dưới 98% thì chuyển sang chia đoạn.
- File lớn xử lý đồng bộ (tối đa 20 MB và 50 trang); làm hàng đợi nền ở bản sau.
- Chưa có che PII (mục G1 trong gap list). File chỉ ở mức A, không ra ngoài, nên chấp nhận được cho bản test.

## 6. Ước lượng
- Code, test và build: khoảng 3–5 giờ máy; build image khoảng 5–15 phút.
- Chi phí LLM: $0 (không có bước nào gọi LLM). Nếu giao Pi làm một phần thì đặt trần DeepSeek $1.
