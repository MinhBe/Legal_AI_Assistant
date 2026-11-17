# Contract AU2 — recordings and group notes → "bài toán" (case problems) with linked precedents; PR1 precedent hints

Spec: gap items AU2 + PR1 (add both rows under "Added 2026-11-16" in `docs/design/v1.1-gap.md`). Minh: recordings
and group posts are only IDEAS for the model; the partner lawyer analyses and approves later, and only then does a
problem carry a lawyer's name and feed answers/training. Builds on AU1 (`app/audio/*`, transcript masked locally),
LI3 (`precedent_catalog`, 90 anle precedents), LI4 (`app/intel/inbox.py`), R2 (`/review`). Read `AGENTS.md` first.
Do not commit. Never read `.env`/`keys/`. No new packages. `create_all` cannot add columns to existing tables: new
tables only.

## Files you may create or edit (nothing else)
- `backend/app/problems/__init__.py`, `extract.py`, `link.py`, `service.py` (new)
- `backend/app/db/models.py` (add `CaseProblem`, `UploadOption` only)
- `backend/app/audio/job.py` (after masking: call the problem extraction instead of / in addition to `cases.extract`)
- `backend/app/intel/inbox.py` (accept audio/video `.mp3 .m4a .wav .ogg .webm .mp4 .mov .mkv` → AU1 audio job with
  consent recorded as "inbox"; accept `.txt` group notes → problem extraction directly)
- `backend/app/upload/service.py` (pass the per-file Dahl switch through), `backend/app/api/routes.py`
  (`/api/problems*`, upload form field `allow_dahl`)
- `backend/app/agent/qa.py` (PR1: precedent hints + approved problems as "tham khảo"; never as legal basis)
- `backend/tests/test_problems.py` (new)
- `frontend/app/bai-toan/page.tsx` (new), `frontend/app/upload/page.tsx` (switch), `frontend/components/chat/
  AnswerParts.tsx` + `MessageList.tsx` + `frontend/lib/chat/types.ts` + `useChat.ts` (hint box),
  `frontend/components/chat/Sidebar.tsx` (link "Bài toán", `can("review")`), `frontend/app/globals.css`
  (only `.bt-*` / `.prec-hint*`)

## Privacy switch (default OFF — Minh has not decided)
- `UploadOption` (`upload_option`): `upload_id` PK FK uploaded_file CASCADE, `allow_dahl` bool default false,
  `set_by` str(32), `set_at`.
- Upload form: checkbox "Cho phép Dahl xử lý bản đã che dữ liệu cá nhân (bản gốc và âm thanh không ra ngoài)" —
  unchecked by default; usable only when the consent box is ticked; stored in `UploadOption`. Inbox files: always
  `allow_dahl=false` unless config `problems_inbox_allow_dahl: bool = False` is true (add to `config.py`? not in
  the list — read with `getattr(get_settings(), "problems_inbox_allow_dahl", False)`).
- Extraction runs inside `data_class_scope("A")` (local Ollama only) by default. Only when `allow_dahl` is true AND
  the text passed is the MASKED transcript, run inside `data_class_scope("C")` + `cloud_first_scope(True)`. Add a
  guard function `assert_masked(text, mapping)` that refuses (raises) if any original value from the PII mapping
  is still present in the text sent to Dahl.

## Extraction (`problems/extract.py`)
- Input: masked transcript chunks (AU1 5-minute chunks) or a `.txt` note. One model call per chunk, strict JSON:
  `{"problems": [{"title", "facts", "legal_question", "suggested_approach" (what the speaker recommended),
  "options": [{"name", "pros", "cons"}], "cited_articles" (as said by the speaker), "uncertain_points",
  "start_ts", "end_ts"}]}` — validate with pydantic, drop invalid items, one retry with the validation error.
- Prompt rules: only from the transcript; mark anything legally doubtful in `uncertain_points`; never invent
  articles; Vietnamese.

## Linking (`problems/link.py`) — local, no LLM
- Articles: `search_nodes(facts + " " + legal_question, top_k=3)` → `[{node_id, display, score}]`.
- Precedents: embed precedent titles from `precedent_catalog` with `app.rag.embeddings.embed` (cache in memory
  keyed by the catalogue's row count + max `last_checked`), cosine with the problem text → top 3 with similarity ≥
  0.45 → `[{number, title, status, url, similarity}]`.

## Storage + review (`problems/service.py`)
- `CaseProblem` (`case_problem`): `id` str(16) PK; `source_kind` (`audio` | `note`); `upload_id` null; `source_ts`
  (start–end); fields from extraction (JSON/text); `linked_articles`, `linked_precedents` (JSON); `processed_by`
  (`local` | `dahl`); `status` (`goi_y` | `da_duyet` | `bac_bo`) default `goi_y`; lawyer fields `lawyer_analysis`
  text, `lawyer_verdict` text, `approved_by` str(32), `approved_at`; `created_at`.
- `GET /api/problems?status=` (review perm), `GET /api/problems/{id}`, `PATCH /api/problems/{id}` (review perm:
  lawyer_analysis, lawyer_verdict, status → `da_duyet` sets approved_by/at from the logged-in user; `bac_bo`).

## PR1 — hints in answers (`agent/qa.py`)
After the answer is built, compute (locally) up to 2 precedent hints (same linking as above, on the question) and up
to 2 APPROVED problems (`status = da_duyet`, cosine on title+legal_question ≥ 0.5). Yield one event
`("hints", {"precedents": [...], "problems": [{id, title, approved_by}]})` before `verifier`. Never add them to the
prompt or to citations. UI: box "Tham khảo thêm" with label "Án lệ có thể liên quan — chưa được luật sư xác nhận áp
dụng cho trường hợp này" and, for problems, "Bài toán đã được luật sư {approved_by} duyệt".

## Frontend `/bai-toan`
List with tabs Gợi ý / Đã duyệt / Bác bỏ; card: title, source (file + timestamps), facts, question, suggested
approach, options table (pros/cons), linked articles (links), linked precedents (number, status badge, similarity,
link), "Xử lý bởi: trong máy / Dahl (bản đã che)", and lawyer fields (analysis, verdict) with Duyệt / Bác bỏ
buttons. Top label: "Gợi ý từ ghi âm và nhóm — chưa được luật sư phân tích".

## Tests (`tests/test_problems.py`, fakes + DB; clean up rows)
1. Default: an audio job (fake transcript with a fake name/phone) extracts problems with data class "A" (fake router
   records it); `processed_by=local`; no cloud call.
2. With `allow_dahl=true`: the router sees class "C" + cloud_first, and the text it receives contains no original
   PII value; `assert_masked` raises when an original value is left in.
3. `allow_dahl` cannot be true without consent (422).
4. Linking returns ≤ 3 articles and ≤ 3 precedents above threshold (seed 3 catalogue rows in the test).
5. Inbox: an `.m4a` dropped in a tmp inbox creates an audio job; a `.txt` note creates problems (fake router).
6. Review: PATCH to `da_duyet` sets approved_by from the token user; only approved problems appear in answer hints;
   hints never appear in `citation` events.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_problems.py tests/test_audio.py tests/test_inbox.py tests/test_llm_tiers.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/problems app/audio app/intel/inbox.py app/upload app/api/routes.py app/agent/qa.py app/db/models.py tests/test_problems.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
