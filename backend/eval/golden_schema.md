# Golden set v2 — lược đồ

Một JSON object mỗi dòng trong `golden_v2.jsonl` (5 nhóm, design v1.1 §11.1).
Sinh lại bằng `python -m scripts.migrate_gold_v2` (idempotent).

| trường | kiểu | ghi chú |
|---|---|---|
| `id` | str | duy nhất; ca cũ giữ mã cũ (`A01`, `E03`…), ca tổng hợp dùng `G<nhóm>-<số>` |
| `group` | int | 1 hỏi đáp, 2 nhiều vấn đề, 3 từ chối, 4 chuyển luật sư, 5 bẫy thời gian |
| `question` | str | câu hỏi tiếng Việt |
| `history` | list | các lượt trước, có thể rỗng |
| `event_date` | ISO hoặc null | ngày xảy ra sự việc; bắt buộc với nhóm 5 |
| `advice_date` | ISO | mặc định `2026-11-16` |
| `facts` | dict | dữ kiện đã tách, có thể rỗng |
| `expected_action` | `answer` \| `refuse` \| `escalate` | |
| `expected_provisions` | list `{node_id, doc_id}` | node Điều/Khoản/Điểm; ca `answer` phải có ít nhất 1 |
| `reviewed` | bool | false cho tới khi luật sư duyệt |
| `source` | str | `gold_v1:<id cũ>` hoặc `synthetic:G3` |
| `note` | str | ghi chú / cảnh báo của người soạn |

Đích số lượng: `TARGETS = {1: 30, 2: 20, 3: 20, 4: 20, 5: 30}`. Hiện chưa đủ — luật sư bổ sung sau.
