# Lộ trình từ nay đến khi xong LawVN v1.1, và cách dùng $4 DeepSeek

Ngày 16/11/2026. Ngân sách: **$4 DeepSeek cho coding + $1 cho thử nghiệm**. Dahl đóng băng, không tính vào đây.
Căn cứ giá và số đo: bench pi-dev B1–B3b (bench/results trong repo pi-dev).

## 1. Nguyên tắc tiêu tiền
- **Ai làm gì:**
  - Claude (phiên này) tự code các phần gấp hoặc khó; không tốn DeepSeek.
  - Pi (`pic`, deepseek-flash:high) làm hàng đợi `v1.1-gap.md`, mỗi lần một mục.
  - Claude review diff của Pi trước khi commit (không tốn DeepSeek).
- **Giá DeepSeek đã đo:**
  - Output gồm cả suy luận: $1.20 / 1M token. Đây là phần tốn nhất.
  - Input không cache: $0.30 / 1M. Đọc cache: $0.006 / 1M, gần như miễn phí.
  - Trên bench: $0.005–0.026 một lượt med/lg. Repo thật lớn hơn nên ước gấp 2–3 lần.
- **Giữ cache cao** (cache lượt đầu khoảng 97%):
  - Luôn chạy Pi từ thư mục `RAG\RAG`.
  - Không đổi skill hay extension giữa chừng.
  - `AGENTS.md` ngắn và cố định.
- **Trần mỗi mục** (vượt trần là dừng mục đó và báo): /sm $0.03 · /med $0.08 · /lg $0.20.
- **Trần tổng:** dừng giao việc mới cho Pi khi đã tiêu $3.20, giữ $0.80 cho sửa lỗi và làm lại.
- **Theo dõi:** sau mỗi mục ghi chi phí (đọc usage trong session của Pi) vào `docs/design/chi-phi.csv`; mỗi ngày báo tổng.

## 2. Lộ trình

| Giai đoạn | Thời gian | Nội dung | Ai làm | DeepSeek (ước) |
|---|---|---|---|---|
| A. Tính năng upload → OCR → KG (U1–U7) | Hôm nay, 16/11 | Theo `upload-ocr-kg-plan.md` | Claude | $0 |
| — Minh tester | 17/11 | Kịch bản 5 bước trong kế hoạch, ghi lỗi | Minh | $0 |
| B0. Sửa lỗi từ buổi tester | 17/11 | Các lỗi Minh ghi | Claude | $0 |
| B1. Hiệu chỉnh Pi trên repo thật | 17/11 | Giao Pi 1 mục nhỏ (G5) để đo chi phí thật trên repo RAG, rồi chỉnh lại ước lượng | Pi | $0.03–0.08 (lấy từ $1 thử nghiệm) |
| C. Giai đoạn 1: Gateway, golden set, cổng eval | 18–19/11 | G3, G1, G4, G2, G6 (+ G5 nếu B1 chưa xong); G7 tìm web để sau cùng | Pi + Claude review | $0.41–0.86 (G7 thêm $0.03–0.08) |
| D. Giai đoạn 2: mô hình thời gian | 19–21/11 | T1, T2, T3, T5, T7, T8; T4 phần code nạp (văn bản gốc do Minh cung cấp) | Pi + Claude review | $0.51–1.06 |
| E. Giai đoạn 3: bàn duyệt luật sư | 21–22/11 | R1, R2, R3, R4, R6, R7; R5 Verifier bằng model để sau cùng | Pi + Claude review | $0.32–0.66 (R5 thêm $0.03–0.08) |
| F. Giai đoạn 4: intake, máy tính, án lệ | 23–25/11 | I1, I2, I4; I3 chỉ phần code (chưa chạy batch LLM) | Pi + Claude review | $0.35–0.70 |
| V. Việc còn sót từ kế hoạch V1–V5 | xen kẽ | VL3 (gộp vào G5), VL4 bật/tắt phòng thủ, VL5 streaming; VL1 và VL6 do Minh, VL2 là lượt đo e2e (chi phí LLM chạy, xem mục 4) | Pi | $0.04–0.11 |
| G. Dự phòng sửa lỗi, làm lại | suốt quá trình | Mục nào trượt cổng thì làm lại một lần | Pi | $0.40–0.80 |
| **Tổng coding** | | | | **$2.03–4.19 chưa gồm G7 và R5; gồm cả hai: $2.09–4.35 (trần $4)** |

Nếu chạm trần $3.20 thì hoãn theo thứ tự: G7 (tìm web), R5 (Verifier bằng model), VL5 (streaming). Số thật sau B1 sẽ quyết định có cần hoãn hay không.

Giai đoạn 5 (thang tự chủ, các agent vận hành) chưa làm vì cần log thật, ít nhất 60–150 ca cho mỗi loại ca. Đây là việc của bản sau.

## 3. $1 thử nghiệm
| Việc | Khi nào | Chi phí ước |
|---|---|---|
| B1: đo chi phí thật của Pi trên repo RAG | 17/11 | $0.03–0.08 |
| E2: suy luận `high` so với `medium` trên 6 bài bench khó (output là phần đắt nhất) | 17/11 | ~$0.35 |
| E1: ponytail so với không ponytail trên bài khó (xác nhận chất lượng) | 18/11 | ~$0.35 |
| Dự phòng | | ~$0.2 |
Nếu E2 cho thấy `medium` vẫn qua gate thì chuyển `pic` sang `medium`. Ước tính tiết kiệm được 20–40% cho các giai đoạn C–F.

## 4. Những việc không dùng $4 (cần quyết riêng)
- **Chi phí chạy sản phẩm:** chat đang dùng router Dahl (đã đóng băng); mục G2 sẽ chuyển sang leo thang theo danh sách nhà cung cấp mà Minh chọn.
- **I3 tạo thẻ án lệ hàng loạt** bằng model mạnh: đây là chi phí dữ liệu, cần ngân sách riêng sau khi có code.
- **VL2, đo lại e2e trên gold 50 câu × 3 lần:** khoảng 150 lượt chat. Dahl đã đóng băng; nếu dùng deepseek-flash thì ước khoảng $0.4–0.6. Cần Minh duyệt riêng.
- **R5, Verifier bằng model khi sản phẩm chạy:** mỗi ca rủi ro cao tốn thêm 1 lượt model trung hoặc mạnh.
- **Việc của người:**
  - Luật sư gán nhãn golden set (G3, T6) và duyệt văn bản luật mới (T4).
  - Minh cung cấp văn bản gốc và chọn danh sách nhà cung cấp LLM (G2).

## 5. Điểm dừng để Minh kiểm
1. Sau giai đoạn A: Minh tester tính năng upload.
2. Sau B1: báo chi phí thật mỗi mục, chỉnh lại bảng ngân sách.
3. Cuối mỗi giai đoạn C–F: báo pass/fail của test và cổng eval, chi phí đã tiêu, chi phí còn lại.
4. Khi đã tiêu $3.20: dừng giao việc mới, báo phần còn lại cần bao nhiêu.
