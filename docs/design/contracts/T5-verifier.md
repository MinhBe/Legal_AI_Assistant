# Contract T5 — code Verifier for answers (citation exists, valid at event date, quotes verbatim)

Spec: `docs/design/LawVN-v1.1.md` §4 (Verifier), §5.3; gap item T5. Depends on T2 (`resolve`, `as_of`, the
`timeframe` event). Read `AGENTS.md` first. Do not commit. Never read `.env`. Pure code, no LLM.

## Files you may create or edit (nothing else)
- `backend/app/agent/verifier.py` (new)
- `backend/app/agent/qa.py`
- `backend/tests/test_verifier.py` (new)
- `frontend/lib/chat/types.ts`, `frontend/lib/chat/useChat.ts`, `frontend/components/chat/AnswerParts.tsx`,
  `frontend/components/chat/MessageList.tsx`, `frontend/app/globals.css` (only new `.verifier*` rules)

## `agent/verifier.py`
`verify(db, result: dict, hits: list[dict], as_of: date) -> dict` where `result` is the parsed LLM JSON
(`summary`, `sections[{title, detail, citation_node_ids}]`, `citation_node_ids`). Checks, in order:
1. **exists**: every cited node_id (global and per section) is in `hits` AND in `legal_node`.
2. **in_force**: every cited node is in force at `as_of`: `provision_version` row with valid_from <= as_of (or
   null) and (valid_to null or > as_of); fall back to `legal_node.effective_from/to` when no version row exists.
3. **quotes**: every quoted span in `summary` and section `detail` — text inside `«…»`, `“…”` or `"…"` that is at
   least 12 characters long — must appear verbatim in the text of at least one cited node of that section (global
   citations for the summary). Compare after collapsing whitespace and unifying quote/dash characters; keep case
   and diacritics.
Returns `{"ok": bool, "checked": int, "problems": [{"check": "exists"|"in_force"|"quotes", "node_id"?: str,
"quote"?: str, "message": str}], "dropped": [node_id…]}` — `message` in Vietnamese, e.g.
"Điều 36 BLLĐ 2012 không còn hiệu lực tại ngày 05/03/2022", "Trích dẫn không khớp nguyên văn: «…»".

## `agent/qa.py`
- After the answer is parsed and before streaming it: `v = verify(db, result, hits, as_of)`.
- Citations failing `exists` or `in_force` are removed from the global list and from sections (they are listed in
  `dropped`). If no valid global citation is left, take the existing rewrite/refusal path.
- Escalation: when `v["ok"]` is false and the request's data class is C, call the generator once more with the
  same messages plus one extra user line "Bản trả lời trước sai căn cứ: {messages}. Chỉ trích các điều có trong
  danh sách và còn hiệu lực tại ngày sự kiện." and verify again; keep the better result (fewer problems). Never do
  this for A/B (no extra call; they stay local anyway, but keep it to one local call).
- Yield `("verifier", v)` right before the `timeframe` event.
- Use a DB session the same way the function already does (open/close in `try/finally`).

## Frontend
- `Msg.verifier?: Verifier`; event `verifier`; `VerifierBadge` under the answer: green "Đã kiểm tra căn cứ: {n}
  trích dẫn hợp lệ" when ok, amber "Đã loại {k} căn cứ không hợp lệ" + expandable problem list when not.

## Tests (`tests/test_verifier.py`)
1. Pure-ish: fake hits + monkeypatched DB lookups (or DB-marked with real nodes): a valid blld2019 citation at
   2022-01-01 → ok; a blld2012 citation at 2022-01-01 → `in_force` problem and dropped; unknown node → `exists`.
2. Quotes: verbatim quote passes; altered quote fails; short quotes (< 12 chars) ignored; whitespace/quote-style
   differences tolerated.
3. `answer_with_citations` with fake router/search: an answer citing an out-of-force node gets it removed, a
   `verifier` event is yielded before `timeframe`, and for class C the generator is called exactly twice; for
   class B (via `data_class_scope("B")`) exactly once.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_verifier.py tests/test_timeframe.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/agent/verifier.py app/agent/qa.py tests/test_verifier.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
