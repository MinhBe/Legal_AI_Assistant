# Contract I1 — structured fact table, ≤ 2 follow-up questions, calculators called from answers

Spec: `docs/design/LawVN-v1.1.md` §8; gap item I1. Depends on T2 (`extract_event_date`, `resolve`), I2
(`app/calc/labor.py`). Read `AGENTS.md` first. Do not commit. Never read `.env`.

## Files you may create or edit (nothing else)
- `backend/app/agent/facts.py` (new)
- `backend/app/agent/qa.py`
- `backend/tests/test_facts.py` (new)
- `frontend/lib/chat/types.ts`, `frontend/lib/chat/useChat.ts`, `frontend/components/chat/AnswerParts.tsx`,
  `frontend/components/chat/MessageList.tsx`, `frontend/app/globals.css` (only new `.facts*` / `.calc-res*`)

## `agent/facts.py`
- `FIELDS`: `contract_type` (khong_xac_dinh_thoi_han | xac_dinh_thoi_han | thu_viec | khong_ro), `term_months`
  (int), `start_date`, `end_date` / `event_date` (ISO), `act` (sa_thai | don_phuong_cham_dut_nld |
  don_phuong_cham_dut_nsdld | ky_luat | no_luong | khac), `monthly_salary` (int VND), `notice_given_days` (int),
  `unemployment_insured_months` (int), `procedure` (free text), `documents` (list of str).
- `extract(router, message: str, convo: str = "") -> dict`: one `router.extract_json(..., task="route")` call
  with a short Vietnamese system prompt that lists the fields and says: fill only what the user stated, never guess,
  return `{"field": {"value": ..., "source": "câu hỏi" | "hội thoại", "confidence": 0..1}}`; drop fields with
  confidence < 0.5. Then **code overrides**: dates from `extract_event_date` win over the LLM's event date; money
  parsed by code from the message (`(\d[\d.,]*)\s*(triệu|tr|đồng|vnđ|vnd)` → int VND) wins over the LLM's
  `monthly_salary`. The message passed in is already PII-masked by the gateway (money may appear as `[TIỀN_n]`
  placeholders — then take the LLM value as is and mark `source: "câu hỏi (đã che)"`, do not try to unmask).
  Errors → `{}` (never block the answer).
- `follow_ups(facts: dict, question: str) -> list[str]`: at most 2 Vietnamese questions, only for decisive missing
  fields, by topic: termination/dismissal → `contract_type`, `start_date`; severance/job loss → `monthly_salary`,
  `start_date`; notice → `contract_type`, `term_months` (only for fixed term). Nothing when not decisive.
- `calculations(facts: dict, question: str, event_date) -> list[dict]`: call `app.calc.labor` functions only when
  every input they need is present: severance or job-loss when the question mentions trợ cấp thôi việc / mất việc
  and salary + start/end dates are known (use `service_years`); notice days when it mentions báo trước and contract
  type is known; unlawful dismissal estimate when act = sa_thai / don_phuong_cham_dut_nsdld and salary is known
  (days_not_working = 0, note it). Each item = `{"kind", "title", **calc_result}`.

## `agent/qa.py`
- Submit `facts.extract` to the pool together with the classifier (same masking/data-class rules; it is a
  `route` task). After the answer is ready: `fx = facts_future.result()`; yield `("facts", {"facts": fx,
  "follow_ups": follow_ups(fx, message)})` and, if any, `("calc", {"items": calculations(...)})` — both before
  `verifier`. Add the calculation lines (value + basis label) as one extra data block in the prompt? **No** — keep
  the LLM out of it; the numbers are shown by the UI only.

## Frontend
- `FactsBox` ("Bảng tình tiết"): rows for present fields with value, source and confidence (as %), missing decisive
  fields shown as "chưa rõ"; follow-up questions as clickable chips that put the text into the composer (reuse the
  existing suggested-question mechanism if there is one; otherwise fill the input via the same path the
  `suggest_rewrite` button uses).
- `CalcBox` ("Kết quả tính"): one card per item with value (VND formatted), steps, basis, version, and the warning
  "Kết quả tính tự động — cần luật sư đối chiếu". Order in the message: summary → FactsBox → CalcBox → sections …

## Tests (`tests/test_facts.py`, fakes only)
1. `extract` with a fake router returning fields with mixed confidence: low ones dropped; code-parsed date and
   money override the LLM; router error → `{}`.
2. `follow_ups`: dismissal question missing contract type and start date → 2 questions; all known → none; never
   more than 2.
3. `calculations`: severance with salary 10 triệu, start 2019-01-01, end 2023-06-30, event 2023-06-30 → value from
   `app.calc.labor.severance` (assert equality with a direct call), basis non-empty; missing salary → no item.
4. `answer_with_citations` with fake router/search: `facts` and `calc` events appear before `verifier`.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_facts.py tests/test_calc.py tests/test_timeframe.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/agent/facts.py app/agent/qa.py tests/test_facts.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
