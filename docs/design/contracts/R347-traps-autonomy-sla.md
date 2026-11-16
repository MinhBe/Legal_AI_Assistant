# Contract R3 + R4 + R7 — trap cases, autonomy level per case type, review SLA

Spec: `docs/design/LawVN-v1.1.md` §9.4, §15.1, §15.5; gap items R3, R4, R7 (R6 deferred, see `hau-kiem.md`).
Depends on R1/R2 (`review_case`, `app/review/service.py`, `/review`). Read `AGENTS.md` first. Do not commit.
Never read `.env`. No LLM. `create_all` cannot add columns to existing tables: do NOT add columns to `ReviewCase`;
add new tables only.

## Files you may create or edit (nothing else)
- `backend/app/review/traps.py`, `backend/app/review/autonomy.py`, `backend/app/review/sla.py` (new)
- `backend/app/review/service.py`, `backend/app/db/models.py` (add `AutonomyLevel`, `DutyStatus` at the end)
- `backend/app/api/routes.py` (hook in `_open_review_case`, chat `done`/`risk` annotation, new endpoints)
- `backend/tests/test_review_extras.py` (new)
- `frontend/app/review/page.tsx`, `frontend/components/chat/MessageList.tsx`, `frontend/lib/chat/types.ts`,
  `frontend/lib/chat/useChat.ts`, `frontend/app/globals.css` (only new `.rv-*` / `.unconfirmed*` rules)

## R4 — case type and autonomy level (`review/autonomy.py`)
- `case_type(question: str) -> str` by keywords on `guard.normalize` text: `cham_dut` (sa thải, đuổi việc, chấm
  dứt, thôi việc), `tien_luong` (lương, thưởng, làm thêm), `nghi_ngoi` (nghỉ phép, nghỉ lễ, thai sản), `ky_luat`,
  `hop_dong` (hợp đồng, thử việc), else `khac`.
- Model `AutonomyLevel` (`autonomy_level`): `case_type` str(32) PK, `level` int default 0, `reason` text,
  `updated_at` timestamptz. Missing row = level 0.
- `get_level(db, ct)`, `set_level(db, ct, level, reason)` (0–3 only), `on_review(db, case)`: when an action is
  `heavy_edit` or `reject` with a label in {`sai_trich_dan`, `sai_phien_ban`, `sai_tinh_toan`} → set that
  type's level to 0 with reason "Tụt về 0 do lỗi nghiêm trọng ({label}) ở ca {id}".
- `service.act` calls `on_review` after a successful action; new auto cases get `case_type` filled (the column
  already exists).
- Chat: the `risk` SSE event gets `case_type` and `autonomy_level`; when level == 1 and the answer was queued,
  add `"unconfirmed": true`. UI: show the chip "Chưa được luật sư xác nhận" on such answers.
- Endpoints: `GET /api/review/autonomy` (all types with level, reason), `PATCH /api/review/autonomy/{ct}`
  `{level, reason}`.

## R3 — trap cases (`review/traps.py`)
- `TRAPS`: 5 fixed trap definitions (question, a deliberately flawed draft answer, the flaw label from
  `ERROR_LABELS`, the correct note). Use clearly labour-law flaws, e.g. draft cites BLLĐ 2012 for an event in 2023
  (`sai_phien_ban`), notice 30 days for an indefinite contract (`sai_tinh_toan`), wrong article number
  (`sai_trich_dan`). Mark every trap text "(ca kiểm tra)" only in the stored `reasons`, never in the question shown.
- `maybe_insert_trap(db)`: after every 20th auto case (count of `source="auto"` cases % 20 == 0), insert one trap
  `ReviewCase(source="trap", case_type=<type>, status="pending", question, reasons=[{"code": "trap", ...}],
  reply=<correct note>)` with the flawed draft stored where `package()` reads the draft for cases without an answer
  record (store it in `reviewer_text` before review, or extend `package()` to read it from the trap definition —
  pick one, keep `package()` working for all sources).
- Catch rate: a trap is "caught" when the action is not `approve`. `stats()` adds `traps: {total, reviewed,
  caught, catch_rate}`. The review list must not reveal which cases are traps (same look as auto cases); the stats
  strip shows the catch rate.

## R7 — SLA and duty (`review/sla.py`)
- `due_at(case) -> datetime`: created_at + 1 working day (skip Saturday/Sunday; 08:00–17:00 Asia/Ho_Chi_Minh is
  NOT needed — just add 24 h and push past weekends), or + 4 h when a reason code is `near_limitation`.
- `overdue(case, now)`. `service.case_row` adds `due_at` and `overdue`.
- Model `DutyStatus` (`duty_status`): `id` int PK (single row id=1), `on_duty` bool default true, `lawyer` str(64)
  default "Luật sư chính", `backup` str(64) default "Luật sư dự phòng", `updated_at`.
- `PATCH /api/review/duty` `{on_duty, lawyer?, backup?}`; `GET /api/review/duty`. When `on_duty` becomes false:
  every `autonomy_level` row is set to 0 with reason "Không có luật sư trực" and chat answers that would be queued
  get `risk.no_lawyer = true` → UI chip "Hiện không có luật sư trực: câu trả lời chưa được gửi duyệt ngay".
- `/review`: due time / "Quá hạn" badge per case (red when overdue), a duty toggle in the header (main + backup
  names), an "Mức tự chủ" panel listing case types with level selectors.

## Tests (`tests/test_review_extras.py`, TestClient + DB; delete rows you create)
1. `case_type` table test.
2. Autonomy: default 0; PATCH sets 1; a heavy_edit with `sai_trich_dan` on a case of that type drops it to 0;
   invalid level → 422.
3. Traps: creating 20 auto cases inserts exactly one trap; approving it → not caught, rejecting another →
   caught; `stats()["traps"]` matches.
4. SLA: Friday 10:00 case → due Monday 10:00; near_limitation → +4 h; overdue flag.
5. Duty off → all autonomy levels 0 and a queued chat answer (pipeline monkeypatched) has `no_lawyer` true.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_review_extras.py tests/test_review_desk.py tests/test_risk.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/review app/api/routes.py app/db/models.py tests/test_review_extras.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
