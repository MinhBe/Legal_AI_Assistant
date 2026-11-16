# Contract T7 — store what each answer was based on (answer record)

Spec: `docs/design/LawVN-v1.1.md` §5.3 last bullet; gap item T7. Depends on T2 (`timeframe` event) and T5
(`verifier` event, if present — handle its absence). Read `AGENTS.md` first. Do not commit. Never read `.env`.
Chats are not stored server-side today (the browser keeps them); this adds one record per legal answer.

## Files you may create or edit (nothing else)
- `backend/app/db/models.py` (add `AnswerRecord` at the end)
- `backend/app/agent/record.py` (new)
- `backend/app/api/routes.py` (`chat()` and two new GET endpoints)
- `backend/tests/test_answer_record.py` (new)
- `frontend/lib/chat/types.ts`, `frontend/lib/chat/useChat.ts`, `frontend/components/chat/MessageList.tsx`,
  `frontend/app/globals.css` (only new `.record*` rules)

## Model `AnswerRecord` (`answer_record`)
`id` str(16) PK (uuid4 hex[:12]); `created_at` timestamptz default now; `thread_id` str(64) nullable;
`request_id` str(16) nullable (metrics request id); `data_class` str(1); `question` text (MASKED);
`answer` text (MASKED); `advice_date` date; `event_date` date nullable; `as_of` date;
`provisions` text (JSON list `[{node_id, doc_id, valid_from, valid_to, text_hash, version_id}]` for every
cited node — look up `provision_version` by provision_key valid at `as_of`, fall back to `legal_node`);
`timeframe` text (JSON), `verifier` text (JSON, nullable); `corpus_snapshot` text (JSON `{last_ingest,
n_documents, n_provisions}`); `prompt_version` str(32); `provider` str(32) nullable; `model` str(128) nullable;
`category` str(32) nullable.

## `agent/record.py`
- `build(ctx: dict, events: list[tuple[str, object]], thread_id: str | None) -> dict | None`: returns None unless
  the events contain a `timeframe` event (i.e. a legal answer). Collects answer text from `token` events,
  citations (global + section) from `citation`/`section`, `timeframe`, `verifier`, `done.category`.
  Question = `ctx["question"]` (already masked by the pipeline); answer re-masked with
  `app.obs.metrics._scrub_pii`-equivalent logic using `ctx.get("_pii_mapping")` (reuse the function, do not copy
  it). Provider/model = the winning LLM call in `ctx["llm"]` (`won` true, else the last call without error).
- `save(db, rec: dict) -> str` inserts and returns the id.
- `get(db, id) -> dict | None`, `list_recent(db, limit=50) -> list[dict]` (newest first, without `answer` text).

## `api/routes.py`
- In `chat().gen()`: keep a list of the (event, data) pairs yielded; after the stream ends without error, call
  `record.build(ctx, events, thread_id)`; if a record is built, save it (own `SessionLocal()`, errors logged and
  ignored — recording must never break chat) and yield one more SSE event `record` `{"id": ...}`.
- `GET /api/answers/{id}` → the full record (JSON fields parsed); 404 if missing.
- `GET /api/answers?limit=50` → `list_recent`.

## Frontend
- `Msg.record_id?: string`; handle event `record`; under the AI message show a small link
  "Hồ sơ tra cứu #{id}" opening `${API_BASE}/api/answers/{id}` in a new tab.

## Tests (`tests/test_answer_record.py`)
1. `build` with a fake ctx/events (name + phone in the original question, mapping present, answer echoes the real
   name): returned record has masked question and answer (no name/phone), provisions for each cited node,
   provider/model of the winning call, `data_class` from ctx.
2. `build` returns None for a refusal (no `timeframe` event).
3. DB: `save` + `get` round-trip; `GET /api/answers/{id}` 200 and 404.
4. `POST /api/chat` with the pipeline monkeypatched to yield a canned legal answer (incl. `timeframe`) emits a
   `record` event and the record exists; when saving raises, chat still finishes without an `error` event.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_answer_record.py tests/test_metrics_pii.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/agent/record.py app/api/routes.py app/db/models.py tests/test_answer_record.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
