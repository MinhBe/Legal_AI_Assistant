# Contract U4 — `uploaded_file` table + upload API

Plan: `docs/design/upload-ocr-kg-plan.md` (step U4). Read `AGENTS.md` first. Do not commit.
Done before you: `app/upload/extract.py` (U2: `extract(data, filename) -> Extraction`, `UnsupportedFile`, `TooLarge`)
and `app/upload/ingest.py` (U3: `make_doc_id`, `ingest_upload`, `delete_upload`).

## Files you may create or edit (nothing else)
- `backend/app/db/models.py` (add one model at the end)
- `backend/app/upload/service.py` (new)
- `backend/app/api/routes.py` (add one section of routes at the end; import what you need)
- `backend/tests/test_upload_api.py` (new)

## Model (`db/models.py`)
`UploadedFile`, table `uploaded_file`: `upload_id` String(32) PK (uuid4 hex); `doc_id` String(64) FK
`legal_document.doc_id` ondelete CASCADE, nullable (null when processing failed); `filename` Text; `mime` String(128);
`sha256` String(64) unique, indexed; `size_bytes` Integer; `pages` Integer; `ocr_pages` Integer; `chars` Integer;
`mean_ocr_conf` Float nullable; `parse_mode` String(16) nullable; `n_nodes` Integer; `n_refs` Integer;
`data_class` String(1) default "A"; `status` String(16) default "pending_review" (pending_review | approved | rejected |
failed); `error` Text nullable; `preview` Text (first 2000 chars of the extracted text); `created_at` DateTime(tz)
server_default now(); `reviewed_at` DateTime(tz) nullable. The table is created by the existing
`Base.metadata.create_all` at startup (local compose Postgres only). Rollback: `DROP TABLE uploaded_file;` plus
`DELETE FROM legal_document WHERE doc_type = 'upload';`.

## Service (`upload/service.py`)
```python
UPLOAD_DIR = Path("/app/data/uploads")
def save_upload(db, data: bytes, filename: str, title: str | None = None) -> UploadedFile: ...
def set_status(db, upload_id: str, status: str) -> UploadedFile: ...   # approved | rejected
def remove_upload(db, upload_id: str) -> None: ...
def to_dict(u: UploadedFile) -> dict: ...                              # JSON-safe, ISO dates
```
- `save_upload`: sha256 of `data`; if a row with that hash exists and is not `failed`, return it unchanged (duplicate
  upload). Otherwise write `UPLOAD_DIR/<sha256><ext>`, run `extract`, then `ingest_upload(db, doc_id=make_doc_id(sha),
  title=title or <filename without extension>, text=..., filename=...)`, and store the counts. `UnsupportedFile` and
  `TooLarge` propagate (the route maps them to 415 / 413). Any other exception during extract/ingest → keep a row with
  `status="failed"` and `error=str(exc)[:500]` and return it.
- `set_status` also updates `legal_document.status` of its doc_id to the same value and sets `reviewed_at`.
- `remove_upload`: `delete_upload(db, doc_id)` (nodes + references go with it), delete the stored file, delete the row.
- Uploads are class A: nothing here may call an LLM or the network.

## Routes (append to `api/routes.py`, section header `# ---------- Tải tài liệu lên (upload → OCR → KG) ----------`)
- `POST /api/uploads` — `file: UploadFile = File(...)`, `title: str | None = Form(None)`. Read at most
  `extract.MAX_BYTES + 1` bytes; empty file → 422; `TooLarge` → 413; `UnsupportedFile` → 415 (detail in Vietnamese).
  Returns `to_dict(row)` (status 200 also for duplicates, with `"duplicate": true`).
- `GET /api/uploads` — list, newest first.
- `GET /api/uploads/{upload_id}` — one row (404 if missing).
- `PATCH /api/uploads/{upload_id}` — body `{"status": "approved" | "rejected"}` (pydantic `Literal`).
- `DELETE /api/uploads/{upload_id}` — 204.
Run the synchronous work in the route body (FastAPI runs `def` routes in a thread pool). Keep the style of the file.

## Tests (`tests/test_upload_api.py`, `@pytest.mark.db`, use `fastapi.testclient.TestClient(app)`)
1. POST `data/samples/upload/hop-dong-lao-dong-mau.docx` → 200, `status == "pending_review"`, `n_nodes ≥ 3`, `n_refs ≥ 2`,
   `data_class == "A"`; POST the same file again → same `upload_id`, `duplicate` true.
2. POST `quyet-dinh-ky-luat-scan.jpg` → `ocr_pages == 1`, `mean_ocr_conf > 0.6`.
3. POST `b"MZ.."` as `x.exe` → 415; empty file → 422.
4. GET list contains the ids; PATCH approved → GET shows approved and `legal_document.status == "approved"`.
5. DELETE → 204; GET → 404; no `legal_node` rows left for that doc_id; stored file gone.
Clean up every upload you create (fixture with `finally`). Do not touch other rows.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_upload_api.py tests/test_upload_ingest.py tests/test_upload_extract.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/upload app/api/routes.py app/db/models.py tests/test_upload_api.py
curl -s -F "file=@data/samples/upload/noi-quy-lao-dong.pdf" http://localhost:8000/api/uploads   # then DELETE it
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
