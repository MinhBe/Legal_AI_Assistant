# Contract R1 — rule-based risk score + automatic review queue

Spec: `docs/design/LawVN-v1.1.md` §9.1, §15.3; gap item R1. Depends on T2 (`timeframe`), T5 (`verifier`), T7
(`answer_record`, `record` event). Read `AGENTS.md` first. Do not commit. Never read `.env`. Pure code, no LLM.

## Files you may create or edit (nothing else)
- `backend/app/agent/risk.py` (new)
- `backend/app/db/models.py` (add `ReviewCase` at the end)
- `backend/app/api/routes.py` (`chat()`: score + queue after the record is saved; read endpoints)
- `backend/tests/test_risk.py` (new)
- `frontend/lib/chat/types.ts`, `frontend/lib/chat/useChat.ts`, `frontend/components/chat/MessageList.tsx`,
  `frontend/app/globals.css` (only new `.risk*` rules)

## `agent/risk.py`
`score(question: str, events: list[tuple[str, object]]) -> dict` → `{"score": int | "inf", "queue": bool,
"reasons": [{"code", "weight", "message"}]}`. Weights (§15.3), each reason at most once:
- `high_stakes` +3: question or answer mentions sa thải / đuổi việc / chấm dứt hợp đồng / bồi thường / trợ cấp thôi
  việc / kỷ luật (match on the diacritic-free lower-case text via `app.agent.guard.normalize`).
- `near_limitation` +3: `timeframe.event_date` is between 11 and 12 months before `advice_date`, or the question
  mentions "thời hiệu" (labour dispute limitation is 1 year for most claims — keep this as a named constant
  `LIMITATION_DAYS = 365`, note "cần luật sư xác nhận" in the message).
- `transition` +2: `timeframe.transition_rules` or `timeframe.upcoming` non-empty.
- `low_retrieval` +2: fewer than 2 citations in the answer, or `done.confidence` is a number < 0.6.
- `verifier` +3: `verifier.ok` is false.
- `sanction_no_rule` +3: a `timeframe.flags` entry mentions "xử phạt".
- `out_of_scope` +inf: `done.category` in (`out_of_corpus`) or the question matches gift/bribery/investigation
  words (quà tặng, hối lộ, biếu, điều tra, khởi tố — diacritic-free match).
- `distress` +inf: crisis words (tự tử, muốn chết, không thiết sống, tuyệt vọng — diacritic-free match).
`queue = score == "inf" or score >= QUEUE_THRESHOLD` with `QUEUE_THRESHOLD = 3`. Messages in Vietnamese.

## Model `ReviewCase` (`review_case`)
`id` str(16) PK; `created_at` timestamptz default now; `answer_id` str(16) nullable (→ `answer_record.id`);
`question` text (masked); `risk_score` str(8); `reasons` text (JSON); `status` str(16) default `pending`
(`pending` | `approved` | `light_edit` | `heavy_edit` | `rejected`); `source` str(16) (`auto` | `user`);
`reviewer_text` text nullable; `diff` text nullable; `error_labels` text nullable (JSON list);
`reviewed_at` timestamptz nullable; `reply` text nullable; `thread_id` str(64) nullable; `case_type` str(32)
nullable. (R2 adds the review actions; this contract only creates cases. All columns are defined now because
`create_all` cannot add columns to an existing table later.)

## `api/routes.py`
- In `chat().gen()`, after the record is saved: `r = risk.score(original_message, events)`; yield SSE `risk`
  with `r`; if `r["queue"]`, insert a `ReviewCase(source="auto", answer_id=record id, question=ctx masked
  question, ...)` and include `"case_id"` in the `risk` event. Errors are logged and never break the chat.
- `GET /api/review/cases?status=pending` → list (newest first); `GET /api/review/cases/{id}` → case + the linked
  answer record (parsed) or 404.

## Frontend
- `Msg.risk?: Risk`; handle event `risk`; when `queue` is true show a chip "Đã chuyển luật sư xem lại
  (điểm rủi ro {score})" with the reasons in a tooltip/expander; when false and score > 0 show a small grey
  "Rủi ro thấp ({score})".

## Tests (`tests/test_risk.py`)
1. Table tests for `score`: each reason fires alone with its weight; combinations add up; "hối lộ" → inf + queue;
   distress words → inf; a plain question with 3 citations and no flags → score 0, no queue.
2. Threshold: exactly 3 → queue; 2 → no queue.
3. `POST /api/chat` with the pipeline monkeypatched to yield a canned answer about "sa thải" (incl. `timeframe`,
   `verifier` ok, 1 citation) → `risk` event with queue true (3 + 2), a `review_case` row exists linked to the
   record; `GET /api/review/cases` lists it; `GET /api/review/cases/{id}` returns the answer record.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_risk.py tests/test_answer_record.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/agent/risk.py app/api/routes.py app/db/models.py tests/test_risk.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
