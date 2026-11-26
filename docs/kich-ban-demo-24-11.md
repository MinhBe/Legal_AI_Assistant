# Kịch bản demo Legal Agentic (24/11/2026)

Link công khai (cùng một hệ thống): https://minhbe--tuvanphapluat.modal.run (Modal) và https://tuvanphapluat-vn.vercel.app (Vercel, chuyển tiếp tới Modal; tên phụ tuvanphapluatvn.vercel.app). Không cần máy nhà bật. Tên tuvanphapluat.vercel.app đã thuộc người khác; Vercel không cho tên có dấu chấm như tuvanphapluat.vn.vercel.app.

## Trước giờ demo

| Khi nào | Việc |
|---|---|
| 23/11 | Chạy thử đủ kịch bản dưới đây một lần, quay video dự phòng (mục cuối). |
| Trước demo 10 phút | Mở link `/demo`. Máy chủ ngủ sau 15 phút không ai dùng; lần mở đầu mất khoảng 1–2 phút. Mở xong thì để tab đó. |
| Trước demo 5 phút | Mở sẵn các tab: `/demo`, `/hieu-he-thong`, `/soan-thao`, `/ra-soat-hop-dong`, `/theo-doi`. |
| Dự phòng | Video quay sẵn trên máy, mở được không cần mạng. |

Đăng nhập admin trên link công khai: tài khoản `admin`, mật khẩu trong `keys/lawvn_admin_password.txt`
(chỉ có trên máy anh). Tài khoản demo khác (`user1`…) vẫn là mật khẩu = tên đăng nhập.

AI trả lời câu hỏi mới trên link công khai chỉ chạy khi đã có secret `lawvn-dahl` trên Modal. Chưa có
thì chỉ 3 câu mẫu ở `/demo` trả lời được (bằng câu trả lời ghi sẵn, có nhãn "Bản ghi sẵn"). Muốn hỏi
câu tự do trước khán giả thì demo bằng máy nhà (`docker compose up -d`, `http://localhost:3000`).

## Kịch bản (khoảng 12 phút)

### 1. Vấn đề (1 phút)
Người lao động và doanh nghiệp nhỏ tra luật lao động mất thời gian. AI chung chung hay trích sai điều
luật, hoặc trích luật đã hết hiệu lực. Legal Agentic trả lời có trích dẫn, và code kiểm từng trích dẫn trước khi hiện.

### 2. Hỏi đáp có trích dẫn: `/demo` (3 phút)
- Bấm "Thai sản". Chỉ ra: câu trả lời chia mục, bảng tình tiết, khung thời gian (luật nào áp dụng ngày
  nào), dòng "Đã kiểm tra căn cứ: 5 trích dẫn hợp lệ".
- Bấm một trích dẫn để xem văn bản gốc.
- Bấm "Sa thải trái luật" nếu còn thời gian.
- Nói: câu có dữ liệu cá nhân chỉ chạy model trong máy (bản fine-tune v1a); chỉ câu luật thuần đã che
  mới được gửi model đám mây.

### 3. Rà soát hợp đồng: `/ra-soat-hop-dong` (2 phút)
- Bấm "Dùng hợp đồng mẫu có lỗi", rồi "Rà soát".
- Kết quả: 7 điểm trái luật, 9 điểm cần sửa. Mỗi điểm có câu trích trong hợp đồng, đề xuất sửa, điều luật căn cứ.
- Nói: chạy bằng luật lập trình sẵn, không gọi AI, không gửi nội dung ra ngoài, cùng đầu vào luôn cùng kết quả.

### 4. Soạn văn bản từ mẫu: `/soan-thao` (2 phút)
- Chọn "Hợp đồng lao động (mẫu theo Điều 21 BLLĐ 2019)", bấm "Soạn".
- Bấm "Điền dữ liệu mẫu" (dữ liệu hư cấu), rồi "Soạn văn bản".
- Chỉ ra: mẫu đã khoá v3, lương tự định dạng "12.500.000 đồng", danh sách căn cứ đánh dấu còn hiệu lực.
- Nói quy trình: luật sư đề xuất → admin chỉnh → khoá (code chặn khoá nếu còn TODO hoặc căn cứ hết
  hiệu lực) → soạn. Sửa sau khi khoá là phiên bản mới.

### 5. Theo dõi văn bản mới: `/theo-doi` (1 phút)
- Chọn lĩnh vực "Lao động", đăng ký. Bảng tin hiện tin khớp kèm lý do khớp.

### 6. Hiểu hệ thống: `/hieu-he-thong` (2 phút)
- 5 bài: Hỏi đáp có trích dẫn, Rà soát hợp đồng, Theo dõi văn bản mới, GenAI soạn văn bản, Thu thập dữ liệu.
- Phím →/← để đi từng bước; mỗi bước ghi rõ "Đã có / Đang làm / Lộ trình".

### 7. Số liệu và câu hỏi (1 phút)
- Kho: 57 văn bản, 22.184 điều–khoản–điểm.
- Bộ 50 câu nội bộ: 88–94% đúng điều luật (đo nội bộ, chờ luật sư soát; nói đúng như vậy).
- Fine-tune v1a (Qwen2.5-7B, Kaggle): trích dẫn đúng 0,636, model gốc 0,691, JSON hợp lệ 100%. Đang
  dùng v1a trong máy. Bước sau: sửa dữ liệu train, không phải train lâu hơn (bản 3 epoch tệ hẳn: 0,164).

## Nếu có sự cố

| Sự cố | Cách xử lý |
|---|---|
| Link không mở / quay mãi | Đợi 2 phút (máy chủ đang thức). Vẫn không được thì chiếu video dự phòng. |
| Trang trống danh sách | Tải lại trang (F5). |
| Câu trả lời báo lỗi kết nối | Dùng 3 câu mẫu ở `/demo` (luôn có bản ghi sẵn). |
| Mất mạng | Chiếu video dự phòng; hoặc chạy máy nhà `http://localhost:3000`. |

## Quay video dự phòng (23/11)

1. Mở link công khai, đợi máy chủ thức.
2. Bấm Win + Alt + R (Xbox Game Bar) để bắt đầu quay cửa sổ trình duyệt; bấm lại để dừng.
   Video nằm trong thư mục Videos\Captures.
3. Quay đúng thứ tự mục 2 → 6 ở trên, nói kèm. Khoảng 8–10 phút.
4. Chép video vào máy dùng để demo và một USB.
