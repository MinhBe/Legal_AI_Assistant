# Hướng dẫn test: tải tài liệu lên → OCR → knowledge graph

Bản đầu, để kiểm thử. Toàn bộ xử lý chạy trong máy, không gọi LLM, không gửi dữ liệu ra ngoài.
Kế hoạch gốc: `docs/design/upload-ocr-kg-plan.md`.

## Chuẩn bị
1. Docker Desktop đang chạy. Ở thư mục repo: `docker compose up -d`.
   Nếu vừa pull code mới có đổi `backend/requirements.txt` hoặc `backend/Dockerfile`, chạy thêm
   `docker compose build api && docker compose up -d api`.
2. Kiểm tra nhanh: `curl http://localhost:8000/health` trả `{"status": "ok", ...}`; mở `http://localhost:3000`.
3. File mẫu (hư cấu, không có dữ liệu thật) ở `data/samples/upload/`:

| File | Dạng | Kỳ vọng |
|---|---|---|
| `noi-quy-lao-dong.pdf` | PDF có lớp chữ | Không cần OCR; nhận cấu trúc Điều/Khoản; dẫn chiếu tới Điều 105, 107, 118, 122, 125 BLLĐ |
| `hop-dong-lao-dong-mau.docx` | Word | Chia đoạn hoặc Điều; dẫn chiếu tới Điều 21, 25, 35, 36, 46, 98 BLLĐ |
| `quyet-dinh-ky-luat-scan.jpg` | Ảnh chụp (nghiêng, nhiễu) | 1 trang OCR, độ tin cậy khoảng 95%; dẫn chiếu tới Điều 122, 125 |
| `quyet-dinh-ky-luat-scan.pdf` | PDF chỉ có ảnh | Như trên, đi qua nhánh OCR của PDF |
| `hoi-dap-noi-bo.txt` | Văn bản thường | Dẫn chiếu tới Điều 35, 127 |

## Cách 1: chạy script tự kiểm (khoảng 1 phút)
```
bash scripts/e2e-upload.sh
```
Script tải 4 file mẫu và kiểm từng bước: trạng thái chờ duyệt mức A, có dẫn chiếu, có OCR với bản scan, graph có cạnh
nối sang BLLĐ 2019. Tiếp theo nó kiểm file trùng, định dạng lạ bị từ chối (415), tài liệu chưa duyệt không lọt vào
tìm kiếm của chat, duyệt được, và xoá sạch. Dòng cuối phải là `KẾT QUẢ: ĐẠT`.
Muốn giữ lại file để xem trên giao diện: `KEEP=1 bash scripts/e2e-upload.sh`.

## Cách 2: test trên giao diện (kịch bản cho tester)
1. Mở `http://localhost:3000/upload` (hoặc bấm nút "Tải tài liệu lên" ở đầu trang chat).
2. Kéo thả hoặc chọn cả 5 file mẫu. Mỗi file hiện "Đang xử lý…" rồi một dòng kết quả.
   - Bản scan mất lâu hơn (OCR khoảng 5–20 giây một trang trên CPU).
3. Kiểm từng dòng trong bảng:
   - Trạng thái **chờ duyệt**, mức **A**.
   - Số trang và số trang OCR: PDF có chữ thì OCR = 0, bản scan thì OCR = 1.
   - Độ tin cậy OCR là phần trăm hiện cho bản scan.
   - Kiểu tách: **Điều/Khoản** hoặc **Đoạn**.
   - Số node, số dẫn chiếu.
4. Bấm vào một dòng để xem chữ đã trích. Với ảnh scan, so dấu tiếng Việt với ảnh gốc.
5. Bấm **Xem trên graph**:
   - Đồ thị chỉ gồm tài liệu đó, nối sang các Điều của BLLĐ 2019.
   - Có dòng "Đang xem tài liệu tải lên: … — chờ duyệt".
   - Bấm một node để xem chi tiết. Bấm "Bỏ lọc" để về đồ thị luật thường; đồ thị này không được lẫn tài liệu chưa duyệt.
6. Mở chat, hỏi: "Nội quy của Công ty TNHH Mẫu An Bình quy định gì về sa thải?". Câu trả lời **không** được trích từ
   tài liệu tải lên, vì tài liệu đang chờ duyệt; chỉ trích BLLĐ. (Câu này có gọi LLM của chat như bình thường.)
7. Quay lại `/upload`:
   - Bấm **Duyệt** một file, trạng thái đổi thành đã duyệt.
   - Bấm **Loại** một file khác.
   - Tải lại cùng một file: hệ thống báo trùng, trả dòng cũ, không tạo bản mới.
8. Bấm **Xoá** từng file. Bảng trống; graph của tài liệu đó trả rỗng.
9. Thử lỗi:
   - Một file `.exe` hoặc `.zip`: phải báo không hỗ trợ.
   - Một file lớn hơn 20 MB: phải báo quá lớn.

## Ghi lỗi
Ghi vào `docs/nhat-ky-test-upload.md` (tạo mới nếu chưa có), mỗi lỗi một dòng: file, bước, kết quả thấy, kết quả mong đợi.
Nếu có, kèm ảnh chụp màn hình hoặc `upload_id`.

## Giới hạn của bản đầu (đã biết)
- OCR bằng tesseract tiếng Việt: ảnh mờ hoặc chữ viết tay sẽ sai dấu. Xem cột độ tin cậy.
- Xử lý ngay trong request, tối đa 20 MB và 50 trang. Chưa có hàng đợi nền.
- Chưa che thông tin cá nhân (mục G1 trong hàng đợi). Tài liệu chỉ nằm trong máy, mức A.
- Tài liệu đã duyệt chỉ vào tìm kiếm khi gọi với `include_uploads=True`. Chat hiện chưa bật tuỳ chọn này; đây là bước sau.
- Dẫn chiếu chỉ tự nối sang "Bộ luật Lao động" (BLLĐ 2019). Nghị định chưa có tên trong bảng nhận diện.

## Hoàn tác
- Xoá mọi tài liệu tải lên: xoá từng dòng trên giao diện, hoặc
  `docker compose exec -T postgres psql -U lawvn -d lawvn -c "DELETE FROM legal_document WHERE doc_type='upload'; DELETE FROM uploaded_file;"`.
- Bỏ hẳn bảng: `DROP TABLE uploaded_file;` (chỉ trên Postgres compose ở máy).
