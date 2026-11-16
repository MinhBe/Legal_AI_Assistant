# Cổng đánh giá (G4)

Cổng chặn hồi quy chất lượng mà không gọi LLM: chi phí $0, chạy được trong CI. Spec:
`docs/design/LawVN-v1.1.md` §11.2–11.4, §15.7. Mã: `backend/app/eval/gate.py`, CLI
`backend/scripts/eval_gate.py`, baseline `backend/eval/gate_baseline.json`.

## Đo gì (trên `backend/eval/golden_v2.jsonl`, dùng mọi dòng, reviewed hay chưa)

- `recall@5`, `recall@8`, `mrr` — dòng `expected_action = "answer"` có điều khoản kỳ vọng:
  `search_nodes(..., as_of=event_date)` có trả về đúng node, hoặc node con của đúng Điều
  (cùng tiền tố `doc-dN`), trong top k không.
- `version_correct` — nhóm 5: top-8 tại `event_date` chứa đúng bản đang hiệu lực **và** không
  chứa Điều của bản kia (Điều của dòng cùng câu hỏi nhưng khác văn bản trong nhóm 5).
- `injection_block` — dòng nhóm 3 có note/source ghi chèn lệnh: tỉ lệ
  `app.agent.guard.looks_like_injection` bắt được (chỉ lớp mẫu, không gọi LLM).
- `pii_leak` — 20 câu giả lập đủ 7 loại thực thể G1 (khai trong `gate.py`): số giá trị PII
  gốc còn sót sau `app.gateway.pii.mask`. Phải bằng 0.
- `upload_isolation` — 5 câu truy vấn cố định không được trả về node của văn bản tải lên
  (`doc_type = 'upload'`) khi gọi `search_nodes` mặc định. Phải là true.

Mỗi chỉ số in kèm `n` (số ca), `n_reviewed` (số ca đã duyệt) và cận sai số `3/n` khi số ca sai
bằng 0 (§11.3); `mrr` là số liên tục nên không có `errors`/`bound`.

**Cổng** — cứng: `version_correct` = 1.0 khi nhóm 5 có ít nhất 1 dòng; `injection_block` không
tụt dưới baseline; `pii_leak` = 0; `upload_isolation` = true. Mềm: `recall@5`, `recall@8`, `mrr`
không tụt quá 0.02 so với baseline (§15.7).

## Chạy và cập nhật baseline

```
docker compose exec -T api python -m scripts.eval_gate              # exit 1 nếu có lỗi
docker compose exec -T api python -m scripts.eval_gate --json       # cho máy đọc
docker compose exec -T api python -m pytest -q tests/test_eval_gate.py
docker compose exec -T api python -m scripts.eval_gate --update-baseline
```

`--update-baseline` ghi ngày, git commit (nếu có), `n` từng chỉ số và toàn bộ metrics. Chỉ cập
nhật khi thay đổi có chủ đích (đổi truy hồi, đổi gold set) và ghi lý do vào commit; baseline
thấp đi nghĩa là chất lượng thật đang thấp đi — đừng cập nhật để cổng xanh.
