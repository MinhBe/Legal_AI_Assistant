# Nhật ký triển khai V1–V5

Nhật ký theo luật số 6 của `docs/ke-hoach-V1-V5.md`: mỗi lỗi thử tối đa 2 lần, lần 3 ghi vào đây rồi báo Minh.

---

## Đối chiếu trước khi bắt đầu (05/11/2026)

Kế hoạch ghi ngày viết 04/11/2026, dựa trên commit `91d0d3c`. Kiểm tra lại trước khi chạy bất cứ bước nào:

- `git log` xác nhận `HEAD` và `origin/main` đang đúng ở `91d0d3c` — khớp hoàn toàn với mốc kế hoạch, không có lệch nhánh. 5 commit sau `88cadd4` (`f5919ef`..`91d0d3c`) là Minh tự sửa README/ảnh trực tiếp trên GitHub, không đụng code backend/frontend — đã xem diff, an toàn.
- Đối chiếu các điểm kế hoạch dựa vào code thật (không đoán):
  - `app/config.py`: `dahl_hedge_after`, `embedder`, `rerank_enabled`, `rerank_model`, `langfuse_enabled`, `langfuse_host` đều đúng như kế hoạch mô tả. `search_mode` **chưa có** — đúng, vì đó là việc V2.2 phải thêm.
  - `app/agent/qa.py`: có `SYSTEM`, `_answer_messages`, `_generate`, `answer_with_citations`; `_POOL.submit(` xuất hiện đúng **3 chỗ** như kế hoạch nói (verdict, issues, answer).
  - `app/llm/router.py`: `_CJK`, `class LLMResult`, `_call_dahl(self, model, messages, temperature, max_tokens, parse, won)` đúng như mô tả.
  - `app/agent/guard.py`: có `looks_like_injection`, `classify`, `CATEGORIES`, `out_of_corpus_notice`, `record_out_of_corpus` — chưa có `filter_chunks` (đúng, đó là việc mới của V5.3-D1), không có tên hàm nào trùng nên thêm vào không xung đột.
  - `scripts/probe_retrieval.py`: có `PROBES`, `article_of()`, `main()` như kế hoạch dùng.
- **1 chỗ lệch nhỏ đã phát hiện:** V3.2 mục 2 ghi "`backend/app/llm/router.py` ... mọi `_POOL.submit(fn, ...)` (**3 chỗ**)" — đếm thật chỉ ra **2 chỗ** (`_race_dahl`: gọi `_call_dahl` trong dict comprehension, và gọi `_hedge`). Khi tới V3.2 sẽ sửa đúng 2 chỗ này, không tìm chỗ thứ 3 không tồn tại.
- Kết luận: kế hoạch đáng tin cậy, không cần viết lại. Tiếp tục theo đúng thứ tự V0 → V1 → …

---

## Baseline V0

Chạy 05/11/2026, commit `91d0d3c`, container `api` vừa khởi động lại (nên đã chờ dòng nạp model embedding trước khi đo).

**Mốc quay lại:** tag git `truoc-v1-v5` tại `91d0d3c`. Backup DB: `../backup/lawvn_truoc_v1v5.dump` (21.812.009 byte, `pg_dump -Fc`).

**`scripts.probe_retrieval` (10 câu probe, mode vector mặc định):**
```
Đúng ở hạng 1: 7/10   Có trong top 8: 10/10
```
Hai câu không đúng hạng 1: "Có bị phạt tiền khi vi phạm kỷ luật lao động không?" (hạng 4) và "Tiền lương làm việc vào ban đêm được tính thế nào?" (hạng 3) — cả hai vẫn lọt top 8. Đây là số nền để so sánh với V2 (hybrid/rerank).

**`underthesea`:** chưa cài (`ModuleNotFoundError`). Khớp bẫy đã biết ở mục 0.3 — V2.1 sẽ thêm vào `requirements.txt`.

**`max_seq_length` của model embedding (vie-v2):** `8192` token — số thật cho câu phỏng vấn L1-01. Ngưỡng này khá rộng so với các model embedding nhỏ (256–512), nên số node bị cắt khi embed (đo chi tiết hơn ở V3.5) nhiều khả năng rất thấp hoặc bằng 0 — sẽ xác nhận bằng số đo thật, không đoán trước.

**`get_settings()`:** `embedder=vie-v2` (đúng điều kiện bắt buộc để đi tiếp), `rerank_enabled=False`, `langfuse_enabled=False`, `dahl_hedge_after=15.0`.
