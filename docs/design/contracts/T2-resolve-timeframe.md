# Contract T2 — resolve(event_date, advice_date) + "Khung thời gian" block in every answer

Spec: `docs/design/LawVN-v1.1.md` §5.2; gap item T2. Depends on T1 (`provision_version`, `transition_rule`,
`legal_link`, `app/amend/versions.py`). Read `AGENTS.md` first. Do not commit. Never read `.env`.
Goal for the demo: a question that mentions a past event date is answered with the law in force on that date, and
the answer shows a time-frame box. The LLM never chooses the law version; code does.

## Files you may create or edit (nothing else)
- `backend/app/amend/timeframe.py` (new)
- `backend/app/agent/qa.py`
- `backend/tests/test_timeframe.py` (new)
- `frontend/lib/chat/types.ts`, `frontend/lib/chat/useChat.ts`, `frontend/components/chat/AnswerParts.tsx`,
  `frontend/components/chat/MessageList.tsx`, `frontend/app/globals.css` (only new `.timeframe*` rules)

## `amend/timeframe.py` (pure code, no LLM)
- `extract_event_date(text: str, advice_date: date) -> tuple[date | None, str]` — returns (date, granularity) with
  granularity `ngày` | `tháng` | `năm` | `""`. Recognise `ngày 20/12/2020`, `20/12/2020`, `20-12-2020`,
  `20.12.2020`, `ngày 20 tháng 12 năm 2020`, `tháng 12/2020` and `tháng 12 năm 2020` (→ the last day of that
  month), `năm 2020` (→ 31/12/2020). Validate day/month ranges. Never match law numbers such as
  `45/2019/QH14`, `145/2020/NĐ-CP`, `Điều 25`. When several dates appear, pick the latest one that is not after
  `advice_date` (the act in dispute usually comes last); if all are in the future, pick the earliest future one.
- `resolve(db, event_date: date | None, advice_date: date) -> dict` with these keys (all dates ISO strings):
  - `event_date`, `event_date_source` (`"câu hỏi"` or `"không nêu — dùng ngày tư vấn"`), `advice_date`, `as_of`
    (= event_date or advice_date).
  - `applicable`: documents (doc_type not `upload`) in force at `as_of` — `{doc_id, title, number}` — from
    `legal_document.effective_date/expired_date`.
  - `changes_after`: documents whose `effective_date` is in (`as_of`, `advice_date`] — `{doc_id, title, number,
    effective_date, replaces: [doc_id…]}` (replaces from `legal_link` link_type `replaces` or `document_relation`).
  - `upcoming`: documents with `effective_date` > `advice_date` or any `provision_version.status` `not_yet_in_force`
    / `pending_amendment` — marked "không dùng làm căn cứ".
  - `transition_rules`: `transition_rule` rows whose `doc_key` is in `changes_after` doc ids —
    `{doc_key, condition, outcome, provision_ref, note}`.
  - `flags`: list of Vietnamese strings. Add "Có văn bản mới sau ngày sự kiện, chưa có quy tắc chuyển tiếp: cần luật
    sư xác nhận" when `changes_after` is non-empty and `transition_rules` is empty; add "Lĩnh vực xử phạt: cần luật
    sư xác nhận" when `resolve` is called with `topic_hint` containing `xử phạt`/`phạt vi phạm` (add an optional
    `topic_hint: str = ""` parameter).
- `summary_lines(tf: dict) -> list[str]`: 2–4 short Vietnamese lines used in the prompt, e.g.
  "Ngày sự kiện: 20/12/2020. Luật áp dụng: Bộ luật Lao động 2012." / "Sau ngày sự kiện: BLLĐ 2019 có hiệu lực
  01/01/2021 (chỉ để cảnh báo, không làm căn cứ)."

## `agent/qa.py`
- In `answer_with_citations`, before retrieval: `event, gran = extract_event_date(message, today)`;
  `tf = resolve(db, event, today, topic_hint=message)`.
- Retrieval uses the event date: pass `search=functools.partial(search_nodes, as_of=event)` when `event` is set
  (keep the current call when it is not).
- `_answer_messages` gets an optional `timeframe_lines: list[str] | None`; when given, add a data block
  `"Khung thời gian (do hệ thống xác định, không tự đổi):\n" + lines` right before the question. Keep the system
  prompt unchanged.
- Yield `("timeframe", tf)` once, after the citations and before `done`, on every legal answer path (also when
  there is no event date). Do not yield it on refusal/injection/off-topic paths.

## Frontend
- `types.ts`: `TimeFrame` type matching the dict; `Msg.timeframe?: TimeFrame`.
- `useChat.ts`: handle event `timeframe`.
- `AnswerParts.tsx`: `TimeFrameBox` — title "Khung thời gian"; rows: "Ngày sự kiện" (+ source), "Luật áp dụng",
  "Thay đổi sau sự kiện", "Sắp thay đổi (không làm căn cứ)", "Điều khoản chuyển tiếp đã xét", flags as warning
  chips. Empty lists show "không có". Dates shown dd/mm/yyyy.
- `MessageList.tsx`: render it for AI messages that have `timeframe`, below the summary and above the sections.
- Run `docker compose exec -T web npx tsc --noEmit` (or `npm run build` if tsc is not set up) — must pass.

## Tests (`tests/test_timeframe.py`)
1. `extract_event_date` table: the formats above; law numbers ignored; several dates → latest past one;
   "năm 2020" → 2020-12-31; "tháng 2/2024" → 2024-02-29; no date → (None, "").
2. DB (`@pytest.mark.db`): event 2020-12-20, advice 2026-11-16 → `applicable` contains `blld2012` and not
   `blld2019`; `changes_after` contains `blld2019`; `transition_rules` has the BLLĐ 2019 seed row; no
   "chưa có quy tắc" flag.
3. DB: event None → `applicable` contains `blld2019` and `nd145_2020`, `changes_after` empty.
4. `answer_with_citations` with fake router + fake search (monkeypatch, no network, no DB writes): a message with
   "bị sa thải ngày 20/12/2020" calls search with `as_of=date(2020,12,20)`, the prompt contains
   "Khung thời gian", and a `timeframe` event is yielded before `done`.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_timeframe.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/amend/timeframe.py app/agent/qa.py tests/test_timeframe.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
