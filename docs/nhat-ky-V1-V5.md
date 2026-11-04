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

---

## V1 — đã làm xong tới [DỪNG-1]

Commit `ed073d6` (gold set) và `535b0c4` (script eval), sau `4f44721` (V0).

- `scripts/make_gold_candidates.py`: in 38 Điều ngẫu nhiên (seed=42) + 10 cặp 2012→2019 đổi nhiều nhất
  (theo `node_supersession.similarity` thật, không đoán) ra `eval/candidates.md`.
- `eval/gold_v1.jsonl`: 50 câu. Mọi mã trong `expected_articles` / `expected_nodes` /
  `expected_articles_as_of` đã kiểm tra tồn tại thật trong `legal_node` — 0 mã thiếu.
  Toàn bộ `reviewed: false`.
- `tests/test_gold_file.py`: 2 passed, gồm `test_gold_ids_exist` chạy trên DB thật.
- `scripts/eval_gold.py`: chạy thử (không ghi vào RESULTS.md vì gold set chưa duyệt):
  - `--mode retrieval` trên cả 50 câu: hit@1=0.72, hit@8=0.98, MRR=0.825, 20,3 giây.
  - `--mode e2e --limit 2 --repeat 1`: 2/2 đúng, 0 lỗi, 48,65 giây trung bình.
  - 1 lỗi gặp và sửa ngay lần thử đầu (lần 1/2 theo luật số 6): `_search` dùng từ khoá `k`
    trong khi `search_with_history` gọi bằng `top_k` — đổi tên tham số cho khớp.
- Toàn bộ repo: `pytest -m "not llm"` 148 passed, 1 skipped; ruff sạch (ngoài 1 lỗi có từ
  trước ở `test_env_example.py`, không thuộc phạm vi V1-V5).

**Ghi chú khi viết gold set:** 2 trong 5 câu nhóm C (thời gian thử việc Điều 25/27, một phần
làm thêm giờ Điều 107/106) có nội dung gần như không đổi giữa 2012 và 2019, chỉ đổi số Điều do
đánh số lại — vẫn là phép thử hợp lệ cho việc "trích đúng phiên bản luật theo thời điểm", nhưng
không minh hoạ được "nội dung luật đổi" như 3 câu C còn lại (tuổi nghỉ hưu, giấy phép lao động,
thỏa ước lao động tập thể). Minh xem lại khi duyệt.

**[DỪNG-1]:** đã gửi `backend/eval/gold_v1.jsonl` cho Minh qua thread. Chờ Minh sửa nội dung và
đổi `"reviewed": false` thành `"reviewed": true` ở từng dòng đã xem qua, rồi báo lại. Sau đó mới
chạy V1.5 (số nền chính thức, ~40 phút) và đưa số vào `docs/ket-qua-do-luong.md`.
