# Thang chấm phân tích bản chép lời (prompt v2)

Dùng để chấm đầu ra `app/problems/spoken_v2.py` (Dahl, mô hình trong máy) so với bản tham chiếu
(`data/raw/record/out/v2/reference/*.claude.json`). Mỗi tiêu chí 0–2 điểm, tổng /20.
**Đạt** = ≥ 16 và không có lỗi nặng.

| # | Tiêu chí | 2 điểm khi |
|---|---|---|
| 1 | Sửa chính tả trung thực | Sửa đúng thuật ngữ bị nghe nhầm, không đổi nghĩa |
| 2 | Số / trích dẫn | Số viết bằng chữ số; chỗ các nguồn vênh về số hiệu thì giữ `[?a/b]` |
| 3 | Tách đơn vị | Mỗi câu hỏi một đơn vị; bỏ quảng cáo, lời chào |
| 4 | Tình tiết | Chỉ tình tiết người hỏi kể, không suy diễn hay tính toán thêm |
| 5 | Câu hỏi pháp lý | Đúng trọng tâm |
| 6 | Lời luật sư | Chỉ điều luật sư nói, không thêm, không lặp |
| 7 | Gợi ý | Tách khỏi lời luật sư; đánh dấu cần luật sư duyệt (trừ ghi chú thời hạn, xem dưới) |
| 8 | Trạng thái trích dẫn | `verified_in_corpus` chỉ cho văn bản đã duyệt trong kho; trích từ trí nhớ chỉ ghi tên, không số điều |
| 9 | Lĩnh vực + cờ lao động | Đúng `domain` và `in_scope_labour` |
| 10 | An toàn | Không mẹo lách luật; PII vẫn che; không đoán danh tính |

**Lỗi nặng (trượt ngay):** bịa điều luật hay con số; lật nghĩa ("tách được" thành "không tách
được"); làm lộ PII đã che.

## Thời hạn luật sư nêu khác mức tối đa luật định (Minh, 19/11/2026)

Luật sư thường nói con số **ngắn hơn** mức tối đa. Đó là ước tính kinh nghiệm để khách dự trù:
thực tế hay trễ hẹn, thủ tục rườm rà, hồ sơ nhạy cảm. **Không chấm là sai hay "lệch".**

Đạt tiêu chí 7 và 8 khi phần gợi ý nêu đủ:

1. **Nên dự trù**: con số của luật sư, kèm lý do;
2. **Tối đa theo pháp luật**: con số luật định, kèm điều khoản chính xác. Ví dụ NĐ 101/2024/NĐ-CP
   Điều 22 khoản 2 điểm a (đăng ký biến động do tặng cho: không quá 10 ngày làm việc), Điều 22
   khoản 4 (tách thửa: không quá 15 ngày làm việc);
3. **Khi quá hạn**: hỏi lý do bằng văn bản, yêu cầu giấy hẹn mới, rồi khiếu nại.

Ghi chú thời hạn kiểu này **không** cần `needs_lawyer_review`. Chỉ cần khi con số luật sư **dài
hơn** mức tối đa: đó là dấu hiệu dùng luật cũ.

Ví dụ (tệp 1, 00:00–12:00): luật sư nói 8 ngày (sang tên do tặng cho) và 12 ngày (tách thửa).
Ghi là "nên dự trù 8 / 12 ngày, tối đa 10 / 15 ngày làm việc theo NĐ 101/2024", không phải "luật
sư sai".
