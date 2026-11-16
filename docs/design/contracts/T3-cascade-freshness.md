# Contract T3 — cascade "cần xác minh" flags + corpus freshness flag

Spec: `docs/design/LawVN-v1.1.md` §5.3; gap item T3; §15.8 thresholds (30 days, 14 for sanctions). Depends on T1
(`legal_link`, `provision_version`) and T2 (`app/amend/timeframe.py`, the `timeframe` event and `TimeFrameBox`).
Read `AGENTS.md` first. Do not commit. Never read `.env`. Pure code, no LLM.

## Files you may create or edit (nothing else)
- `backend/app/amend/cascade.py` (new)
- `backend/app/amend/timeframe.py` (add the two flag sources to `resolve`, nothing else)
- `backend/app/api/routes.py` (one new read-only endpoint)
- `backend/tests/test_cascade.py` (new)
- `frontend/components/chat/AnswerParts.tsx` (show `verify` items in `TimeFrameBox`, nothing else)
- `frontend/lib/chat/types.ts` (add the `verify` field type)

## `amend/cascade.py`
- `FRESH_DAYS = 30`, `FRESH_DAYS_SANCTION = 14`.
- `needs_verification(db, as_of: date, doc_ids: list[str] | None = None) -> list[dict]`: for every `legal_link`
  with link_type `guides` or `based_on` whose target document (`to_key`, a doc_id, or the doc of a node key) is no
  longer in force at `as_of` (`expired_date` <= as_of, or a `replaces` link points at it with valid_from <= as_of)
  while the source document is still in force at `as_of`, return
  `{doc_id, title, base_doc_id, base_title, since, reason}` with reason
  "Văn bản gốc {base_title} đã bị thay từ {dd/mm/yyyy}: cần xác minh văn bản này còn áp dụng không".
  `doc_ids` limits the result to those source documents. Never change any status in the database.
- `corpus_freshness(db, today: date, topic_hint: str = "") -> dict`: `last_ingest` = latest
  `legal_document.created_at` (date part) over documents whose doc_type is not `upload`; `threshold` =
  `FRESH_DAYS_SANCTION` if `topic_hint` mentions `xử phạt` / `phạt vi phạm`, else `FRESH_DAYS`;
  `stale` = (today - last_ingest).days > threshold; `message` = "Kho văn bản nạp lần cuối {dd/mm/yyyy} (quá {n}
  ngày): có thể chưa cập nhật văn bản mới" when stale, else "".

## `amend/timeframe.py`
- `resolve` adds key `verify`: `needs_verification(db, as_of, [d["doc_id"] for d in applicable])`.
- When `corpus_freshness(...).stale`, append its `message` to `flags`.

## `api/routes.py`
- `GET /api/law/verify?as_of=YYYY-MM-DD` → `{"as_of", "items": needs_verification(...), "freshness":
  corpus_freshness(...)}` (default as_of = today).

## Frontend
- `TimeFrameBox`: new row "Cần xác minh (văn bản dựa trên luật đã bị thay)" listing `verify[].reason`; "không có"
  when empty.

## Tests (`tests/test_cascade.py`, DB tests marked `@pytest.mark.db`; insert test rows inside a transaction or
with unique test doc_ids and delete them in a fixture finaliser — leave the database as it was)
1. A test document `test_guide_doc` (in force) with `legal_link` `guides` → `blld2012`: `needs_verification` at
   2022-01-01 returns it with since 2021-01-01; at 2020-06-01 returns nothing.
2. The real corpus at today: `nd145_2020` guides `blld2019` (in force) → not flagged.
3. `corpus_freshness` with `today` = last_ingest + 31 days → stale, message mentions the date; + 10 days → not
   stale; sanction hint uses 14 days.
4. `resolve(...)` includes `verify` and the freshness flag when stale (call with a far-future `advice_date`).
5. `GET /api/law/verify` returns 200 and the keys above (FastAPI TestClient).

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_cascade.py tests/test_timeframe.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/amend app/api/routes.py tests/test_cascade.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
