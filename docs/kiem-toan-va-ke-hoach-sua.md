# Kiểm toán sau V1–V6 và kế hoạch sửa

Viết ngày 05/11/2026, trên 10 commit chưa push (`4f44721`..`cf2f3e3`), gốc `91d0d3c`.
Mục đích: liệt kê **đúng những gì đang sai hoặc yếu**, rồi xếp thứ tự sửa. Không có số nào trong tài liệu này là ước đoán; mỗi mục đều chỉ ra bằng chứng.

---

## A. Những lỗi làm số đo hiện tại **không dùng được để nói trước nhà tuyển dụng**

### A1. Gold set chưa ai duyệt, và đã tìm thấy ít nhất 1 nhãn sai
- **Bằng chứng:** `E03` ("Thủ tục nộp đơn khởi kiện tranh chấp lao động ra tòa án gồm những bước nào?") bị gắn `expect: refuse`, nhưng BLLĐ 2019 có hẳn Chương XIV về giải quyết tranh chấp lao động (Điều 179–190). Hệ thống trích Điều 188, 190 — tức là **hệ thống đúng, nhãn sai**.
- **Hệ quả:** mọi tỉ lệ "từ chối đúng" đang bị tính sai ít nhất 1/5 câu nhóm E.
- **Chưa kiểm:** 49 câu còn lại chưa ai soát. Tỉ lệ nhãn sai thật sự chưa biết.

### A2. Tỉ lệ "từ chối đúng" của V1/V4 đo bằng quy tắc cũ
- **Bằng chứng:** `E05` (đăng ký hộ kinh doanh) bị tính là sai, nhưng chạy tay cho thấy hệ thống trả lời đúng bằng lời nhắc lạc đề (`category: off_topic`). Bộ đo cũ chỉ tính câu từ chối và thẻ chuyển chuyên gia.
- **Đã sửa bộ đo** (`eval_gold.py` tính `off_topic`/`injection` là từ chối đúng), **nhưng chưa chạy lại** V1 base và V4. Con số 0,60 trong `ket-qua-do-luong.md` là số cũ.

### A3. Kết quả V5 không chứng minh được điều gì
- **Bằng chứng:** ASR = 0/15 ở **cả 4 cấu hình**, kể cả khi **không bật phòng thủ** nào.
- **Hệ quả:** không thể nói "lớp phòng thủ của em giảm tấn công từ X xuống Y", vì X đã bằng 0. Phép thử hiện quá yếu: 5 payload đều là câu lệnh lộ liễu, và model nền vốn đã bỏ qua.
- Đây là **giới hạn của phép thử**, không phải bằng chứng hệ thống an toàn.

### A4. Số liệu trong `data/metrics` bị trộn giữa các lần chạy cùng tag
- **Bằng chứng:** `metrics_report --tag v3-hedge5` trả về 50 request, trong khi lượt đó chỉ chạy 25 câu (`--only A`). Nguyên nhân: lượt hedge chạy 2 lần (trước và sau khi sửa lỗi cache) và cùng ghi tag `v3-hedge5`.
- **Hệ quả:** mọi thống kê lọc theo tag có thể gộp nhầm 2 lần chạy. Các số trong `ket-qua-do-luong.md` lấy từ file JSON kết quả (đúng), nhưng số lấy từ `metrics_report` theo tag thì cần kiểm lại.

---

## B. Những chỗ tài liệu/dự án nói **mạnh hơn sự thật**

### B1. "Streaming" không phải là streaming token
- **Bằng chứng:** `ttft_s` p50 = `total_s` p50 = 16,1 giây trong `v3-metrics`. Lý do: router phải đợi model trả lời **trọn vẹn** rồi mới bỏ phần `<think>` và chấm JSON; `qa.py` sau đó cắt câu trả lời thành đoạn rồi mới phát ra.
- **Thực tế:** truyền tải bằng SSE là thật, nhưng người dùng **không thấy chữ chạy dần** — họ chờ 16 giây rồi thấy cả câu.
- README đang ghi "SSE streaming" ở bảng công nghệ, dễ bị hiểu thành token streaming.

### B2. Độ nhất quán thấp, chưa được nêu ở đâu
- **Bằng chứng:** chỉ **62%** câu trích đúng cùng bộ điều luật ở cả 3 lần chạy (`v4-v1`), và 44% ở lượt `v1-base-e2e`.
- Đây là con số quan trọng khi nói về "capability so với reliability", nhưng chưa có trong README hay tài liệu kết quả.

### B3. Hai chỉ số trong README chưa cập nhật theo số đo mới
- README đang ghi "18/18 câu trích đúng Điều" từ bộ đo cũ 18 câu. Bộ gold 50 câu cho **88–94%**, không phải 100%.

---

## C. Nợ kỹ thuật

### C1. Lịch sử commit không chạy được ở từng bước
- **Bằng chứng:** `b3ab1ce` sửa `routes.py` thêm `from app import prompts`, nhưng `app/prompts/` chỉ xuất hiện ở `df3a893`. Checkout `b3ab1ce` sẽ lỗi import.
- Cần gộp hoặc đổi thứ tự trước khi push.

### C2. `git bisect` và test không che được đường chạy mặc định mới
- Các cờ `search_mode`, `rerank_enabled`, `inj_*`, `qa_prompt_version` đều có test ở mức đơn vị, nhưng **không có test nào chạy `search_nodes(mode="hybrid")` trên DB thật**. Nếu hybrid hỏng, chỉ phát hiện khi chạy eval tay.

### C3. Langfuse: đã chạy nhưng chưa có trong tài liệu và chưa tự bật lại
- Đã tạo tài khoản dev, project `luat-lao-dong`, API key, ghi vào `.env` (gitignore). Kiểm chứng: 1 trace, 8 generation.
- `.env.example` chưa có hướng dẫn 4 biến Langfuse; người khác clone về sẽ không biết cách bật.

---

## D. Những chỗ *đúng* và nên giữ

- Quyết định giữ `vector` và tắt rerank đi đúng luật viết trước khi nhìn số (rerank tăng hạng 1 10 điểm nhưng p95 tăng ~19,6 giây trên CPU).
- Quyết định giữ prompt v1 cũng đi đúng luật (v2 không tăng `clause_ok`, lại giảm độ nhất quán 86% → 78%).
- Dương tính giả của bộ lọc D1 = 0/3083 node luật và 0/150 án lệ, sau khi bỏ mẫu URL.
- `race_overhead` = 1,33 và phép so sánh một model (giảm 33% token, chậm thêm p50 1,4 giây) là số thật, dùng được.
- 0/3083 node vượt `max_seq_length` 8192 → không có node nào bị cắt khi embed.

---

## E. Kế hoạch sửa, theo thứ tự

Thứ tự đặt theo: *cái gì làm số đo sai thì sửa trước, cái gì chỉ là tiện nghi thì sau.*

| # | Việc | Vì sao trước/sau | Ước lượng |
|---|---|---|---|
| **E1** | Anh soát 50 câu gold, sửa nhãn sai (bắt đầu từ `E03`), đổi `reviewed: true` | Mọi số khác đều dựa lên đây. Không ai ngoài anh quyết được nhãn đúng | 30 phút của anh |
| **E2** | Chạy lại V1 base e2e và V4 (v1, v2) với bộ đo từ chối đã sửa | A2 — số "từ chối đúng" hiện sai | 2,5 giờ máy, chạy nền |
| **E3** | Gộp `b3ab1ce` + `df3a893` thành 1 commit (hoặc đổi thứ tự) | C1 — lịch sử phải chạy được từng bước trước khi push | 10 phút |
| **E4** | Sửa README: nói rõ "SSE, không phải token streaming"; thay "18/18" bằng số gold 50 câu; thêm độ nhất quán 62% | B1, B2, B3 — tránh nói quá khi phỏng vấn | 20 phút |
| **E5** | Thêm `.env.example` 4 biến Langfuse + 1 đoạn hướng dẫn bật | C3 | 10 phút |
| **E6** | Thêm test DB cho `search_nodes(mode="hybrid")` và `mode="bm25"` | C2 | 20 phút |
| **E7** | Làm mạnh phép thử chèn lệnh: payload tinh vi hơn (giả dạng trích dẫn luật, tiếng Anh lẫn tiếng Việt, lệnh gián tiếp qua "ghi chú của ban soạn thảo") | A3 — để con số ASR có ý nghĩa | 1 giờ + 30 phút chạy |
| **E8** | Sửa `metrics_report`: cảnh báo khi 1 tag có nhiều lần chạy khác nhau | A4 | 20 phút |
| **E9** | (Tùy chọn) Bật streaming thật: cho model thắng stream thẳng ra SSE khi không cần parse JSON | B1 — nếu muốn nói "streaming" đúng nghĩa | 2–3 giờ |

**Đề xuất:** làm E3 → E4 → E5 → E6 → E8 ngay (đều là việc nhỏ, không phụ thuộc gold set), song song chờ anh làm E1. Có E1 rồi thì chạy E2. E7 và E9 làm sau cùng.
