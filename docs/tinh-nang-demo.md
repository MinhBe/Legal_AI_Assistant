# Tính năng demo được — bản hiện tại (commit `25815b4`)

Kiểm tra trực tiếp trên hệ thống đang chạy lúc viết tài liệu này (không liệt kê cái chưa chạy thử). Chạy local: `docker compose up -d`, truy cập `http://localhost:3000`.

---

## Phần demo được ngay — kịch bản gợi ý

### 1. Hỏi đáp pháp luật lao động có trích dẫn (`localhost:3000`)
- Hỏi một câu luật thường ("Thời gian thử việc tối đa là bao lâu?") → trả lời có mục, trích đúng Điều–Khoản–Điểm, xem văn bản gốc khi bấm vào trích dẫn.
- Hỏi lại bằng từ ngữ đời thường ("bị đuổi việc không lý do") → hệ thống không trả lời bừa, mà **đề xuất lại câu hỏi đúng thuật ngữ luật** kèm nút "Dùng câu này".
- Hỏi nối tiếp ("thế còn trường hợp...") → hiểu đúng ngữ cảnh câu trước, không hỏi lại từ đầu.
- Hỏi tình huống dài, nhiều vấn đề (vd. một câu chuyện tranh chấp thật, trên 60 từ) → tự tách thành từng vấn đề pháp lý, trả lời từng phần, nói rõ phần nào ngoài phạm vi.
- Hỏi về luật theo thời điểm cũ ("tuổi nghỉ hưu năm 2015 là bao nhiêu") → tự chuyển sang trích BLLĐ 2012 thay vì 2019.
- Hỏi câu lạc đề (thời tiết, chính trị, chèn lệnh kiểu "bỏ qua hướng dẫn trước đó") → từ chối lịch sự, không bị dắt mũi.
- Hỏi câu đúng phạm vi lao động nhưng ngoài kho văn bản (vd. "luật lao động 2026 nói gì") → báo rõ chưa có văn bản này, **chuyển sang quy trình phê duyệt**.

### 2. Phê duyệt có người thật (human-in-the-loop)
- Từ câu hỏi "ngoài kho" ở trên, bấm nút chuyển chuyên gia → mở `/dashboard` → nhập câu trả lời chuyên gia hoặc từ chối kèm lý do → quay lại khung chat, thẻ tự cập nhật kết quả không cần tải lại trang.

### 3. Knowledge Graph (`localhost:3000/graph`)
- Đồ thị quan hệ Văn bản → Chương → Điều → Khoản → Điểm, tự thu phóng vừa khung.
- Gõ từ khoá để tìm và làm nổi vùng liên quan trên đồ thị.
- Đổi nhóm theo Chương hoặc theo Văn bản; bản đồ ontology bên phải lọc theo triplet (chủ ngữ–vị ngữ–tân ngữ).

### 4. Dashboard vận hành (`localhost:3000/dashboard`)
- Tình trạng hệ thống: 3083 node luật, nhà cung cấp LLM nào đang sống.
- Danh sách yêu cầu chờ phê duyệt, lịch sử hội thoại gần đây.

### 5. Chế độ ẩn: Ôn phỏng vấn kỹ thuật (`localhost:3001`)
- Cùng giao diện chat, nhưng nguồn trả lời là **221 câu hỏi phỏng vấn AI/RAG/LLM** (13 nhóm chủ đề), không phải luật lao động.
- Có đồ thị và bản đồ ontology riêng cho bộ câu hỏi này ở `/graph` trên cổng 3001.
- Phù hợp khi muốn minh hoạ "cùng một kiến trúc RAG, đổi nguồn dữ liệu thì dùng được việc khác" — nhưng đây là tính năng **ẩn, không đưa vào README công khai** theo anh đã dặn trước đó.

### 6. API / Swagger (`localhost:8000/docs`)
- Soạn quyết định kỷ luật (NĐ 30) và xuất file Word.
- Tổng hợp báo cáo nhiều văn bản, tổng hợp án lệ liên quan.
- Tra cứu luật theo đúng ngày hiệu lực (`/api/law_as_of`).

### 7. Quan sát vận hành — Langfuse (`localhost:3002`)
- Xem từng lần hỏi thành một "trace": model nào được gọi, model nào thắng cuộc đua, bao nhiêu token, bao lâu.
- Đăng nhập `dev@localhost.local`, mật khẩu trong `.env` (đã tạo sẵn, không cần đăng ký tay).

---

## Bản cũ và bản mới khác nhau ở đâu

**"Bản cũ"** = trạng thái trước phiên làm việc hôm nay, commit `91d0d3c`.
**"Bản mới"** = sau khi đẩy hôm nay, commit `25815b4`.

Cả hai bản **giống hệt nhau về những gì người dùng cuối thấy và trải nghiệm** — không có tính năng mới nào lộ ra ngoài, không có hành vi trả lời nào đổi khác. Khác biệt nằm ở phần đo lường, hạ tầng kỹ thuật và tài liệu đứng sau sản phẩm:

| | Bản cũ (`91d0d3c`) | Bản mới (`25815b4`) |
|---|---|---|
| **Số liệu chất lượng** | Đo tay trên 18 câu mẫu tự chọn | Bộ 50 câu có đáp án đúng biết trước (6 nhóm tình huống), đo được 88–94% đúng, 73% đúng tới cấp Khoản |
| **Theo dõi mỗi lần gọi LLM** | Không có | Mỗi lần gọi ghi lại token, độ trễ, model nào thắng; xem qua Langfuse hoặc file JSON |
| **Tìm kiếm văn bản** | Chỉ có vector (ngữ nghĩa) | Đã thử thêm BM25 (từ khoá) và kết hợp cả hai (hybrid); đo xong và **quyết định giữ vector** vì không tốt hơn rõ rệt — nói được "đã thử, có số liệu, không phải đoán" |
| **Reranker (xếp lại kết quả)** | Chưa thử | Đã thử, tăng độ chính xác nhưng chậm thêm ~18 giây trên CPU — **quyết định không bật**, nói được đánh đổi tốc độ/chất lượng bằng số thật |
| **So sánh phiên bản câu lệnh AI (prompt)** | Một bản prompt cố định | Hạ tầng so sánh 2 bản, đo xong, **giữ bản gốc** vì bản mới không tốt hơn |
| **Phòng thủ chèn lệnh gián tiếp** | Chỉ có lớp chặn trực tiếp (câu hỏi người dùng) | Thêm lớp mới nhắm vào chèn lệnh ẩn trong văn bản truy hồi (3 kỹ thuật), đã viết code, **đang tắt mặc định**, tạm dừng kiểm thử sâu hơn theo chỉ đạo |
| **Bộ test tự động** | 146 test | 165 test (hybrid, reranker, đo lường, phiên bản prompt) |
| **Tài liệu kỹ thuật** | Không có tài liệu đo lường | 3 tài liệu mới: kế hoạch đo, kết quả đo kèm nguồn dẫn chứng, báo cáo tự kiểm toán và việc cần sửa |

**Nói ngắn gọn khi demo:** bản mới không thêm tính năng cho người dùng thấy, mà thêm phần "chứng minh được" — mọi quyết định kỹ thuật (giữ cách tìm kiếm cũ, không bật reranker, giữ prompt gốc) đều có số đo đứng sau, không phải cảm tính. Đây là điểm mạnh để trả lời khi nhà tuyển dụng hỏi sâu "sao biết cách này tốt hơn cách kia".

**Còn thiếu để nói chắc:** gold set 50 câu đo ở trên vẫn do AI viết, **chưa được anh soát lại** — nên khi demo, nói số liệu là "đo nội bộ, đang chờ duyệt" thay vì khẳng định chắc chắn.
