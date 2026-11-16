# Contract U9 — recognise references to decrees/laws by number + process uploads in the background

Spec: `docs/design/upload-ocr-kg-plan.md` (follow-ups). Read `AGENTS.md` first. Do not commit. Never read `.env`.
No new packages, no LLM.

## Files you may create or edit (nothing else)
- `backend/app/ingestion/references.py`
- `backend/app/upload/ingest.py`, `backend/app/upload/service.py`
- `backend/app/api/routes.py` (only `create_upload`)
- `backend/tests/test_references.py` (add tests), `backend/tests/test_upload_api.py` (adapt + add tests)
- `frontend/app/upload/page.tsx`
- `scripts/e2e-upload.sh` (only to poll until the status leaves `processing`, if it needs that)

## 1. References by document number or name
Today `references.py` resolves only "Bộ luật Lao động" / "Bộ luật này". Add:
- `extract_refs(..., known_docs: dict[str, str] | None = None)`: map of normalised key → doc_id. Keys come from
  `legal_document.number` (e.g. `145/2020/nđ-cp`, `45/2019/qh14`) and short names.
- Recognise after a reference (`RE_DOC_AFTER`) and as inherited context (`RE_DOC_ANY`):
  "Nghị định 145/2020/NĐ-CP", "Nghị định số 145/2020/NĐ-CP", "NĐ 145/2020", "Nghị định 145", "Bộ luật Lao động
  2012", "Bộ luật Lao động năm 2012", "BLLĐ 2019", "Luật số 45/2019/QH14". Year-qualified Bộ luật Lao động picks that
  year's doc (`blld2012` / `blld2019`); bare "Bộ luật Lao động" keeps today's behaviour.
- A doc mentioned without an article ("theo Nghị định 145/2020/NĐ-CP") is not a node reference — ignore it unless
  an `Điều` is attached.
- `known_docs_from_db(db) -> dict[str, str]` helper builds the map from `legal_document` (doc_type not `upload`).
- Existing behaviour and all existing tests in `test_references.py` must stay green.
- `upload/ingest.py` passes `known_docs_from_db(db)` to `extract_refs`; references to nodes that do not exist are
  still dropped (current behaviour).

## 2. Background processing
- `POST /api/uploads` saves the file and a row with `status = "processing"` and returns immediately (HTTP 202 with
  the row). Extraction/OCR/ingest runs in FastAPI `BackgroundTasks` with its own DB session (`SessionLocal()`), then
  sets `pending_review` or `failed` exactly as today. Duplicates (same sha256, not failed) still return the old row
  at once with `duplicate: true` and HTTP 200.
- Split `service.save_upload` into `register_upload(db, data, filename, title) -> (row, is_new)` and
  `process_upload(upload_id, data, filename, title)` (opens and closes its own session). Keep a
  `save_upload(...)` wrapper that does both synchronously (tests and scripts may use it).
- Too-large / unsupported files are still rejected synchronously (check size and extension/magic before
  registering) with 413 / 415 as today.
- Upload page: rows with status `processing` show "Đang xử lý…"; the page polls `GET /api/uploads` every 2 s while
  any row is `processing` and stops when none is.

## Tests
- `test_references.py`: each phrase above resolves to the right doc_id with a `known_docs` map; bare doc mention
  without Điều gives no reference; "Bộ luật Lao động 2012" → `blld2012`.
- `test_upload_api.py`: adapt existing tests to the 202 + background flow (TestClient runs background tasks before
  returning, so the follow-up `GET` sees the final status); add one test that the POST response status is
  `processing` or the final status, and one that a text containing "khoản 1 Điều 3 Nghị định 145/2020/NĐ-CP"
  produces a `node_reference` to `nd145_2020-d3-k1` when that node exists.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_references.py tests/test_upload_api.py tests/test_upload_ingest.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/ingestion/references.py app/upload app/api/routes.py tests/test_references.py tests/test_upload_api.py
docker compose exec -T web npx tsc --noEmit
bash scripts/e2e-upload.sh
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
