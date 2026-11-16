# Contract TPL1 — templates (biểu mẫu): separate upload type with metadata, searchable list

Spec: gap item TPL1. Minh: "sau này tôi còn cần upload cả template lên nữa". Templates (mẫu hợp đồng lao động,
quyết định chấm dứt, đơn, biên bản…) are files people reuse, NOT legal text: they must never enter legal-article
retrieval (`search_nodes`) or the knowledge graph. Auto-fill comes later (not in this contract). Read `AGENTS.md`
first. Do not commit. Never read `.env`. No new packages (`python-docx`, `pypdfium2` and the standard library are
enough; XLSX: read only the file name/size and sheet names with `zipfile` + `xml.etree`, no openpyxl).

## Files you may create or edit (nothing else)
- `backend/app/templates_lib/__init__.py`, `backend/app/templates_lib/service.py` (new — not `templates` to avoid
  clashing with web frameworks' template folders)
- `backend/app/db/models.py` (add `Template` only)
- `backend/app/api/routes.py` (new `/api/templates*` endpoints)
- `backend/tests/test_templates.py` (new)
- `frontend/app/bieu-mau/page.tsx` (new), `frontend/components/chat/Sidebar.tsx` (one link "Biểu mẫu" for
  `can("upload")` users; read-only list visible to `can("review")`), `frontend/app/globals.css` (only `.tpl-*`)

## Model `Template` (`template`)
`id` str(16) PK; `name` text; `kind` str(24) — `hop_dong` | `quyet_dinh` | `don` | `bien_ban` | `thong_bao` |
`quy_che` | `khac`; `description` text null; `legal_basis` text (JSON list of node_ids, validated against
`legal_node`, unknown ids rejected with 422); `filename`; `mime`; `size_bytes`; `sha256` (unique); `text_preview`
text (first 1 500 chars of extracted text, for search); `placeholders` text (JSON list of `{{…}}` / `[…]` / `……`
fields found in the text — just detected, not filled); `version` int default 1; `status` (`active` | `archived`);
`created_by` str(32); `created_at`, `updated_at`.
Files stored under `/app/data/templates/<sha256>.<ext>` (`data/templates/` must be gitignored — check `.gitignore`
and add the line if missing; you may edit `.gitignore` for that one line).

## API (upload/edit = permission `upload` (admin/dev); list/download = `review`; anonymous/guest/user → 401/403)
- `POST /api/templates` (multipart: file, name, kind, description?, legal_basis? comma-separated node_ids) → 201;
  `.docx .pdf .xlsx .doc` only, ≤ 20 MB; duplicate sha → 409 with the existing id.
- `GET /api/templates?q=&kind=&status=active` → list (search `q` in name, description, text_preview,
  diacritics-insensitive via `guard.normalize`).
- `GET /api/templates/{id}` (metadata incl. placeholders, legal basis with `display` of each node),
  `GET /api/templates/{id}/file` (download with the original filename), `PATCH /api/templates/{id}` (name, kind,
  description, legal_basis, status), `POST /api/templates/{id}/file` (new version: replaces the file, version+1),
  `DELETE /api/templates/{id}` (archive; `?hard=true` deletes the row and file).

## Frontend `/bieu-mau`
Upload form (file, name, kind select with Vietnamese labels, description, legal basis picker: free text of node
ids with a "kiểm tra" button that calls `/api/law/{node_id}`), list with search box + kind filter, each row: name,
kind, version, legal basis chips (link to `/api/law/{id}`), placeholders count, download, archive. A note line:
"Biểu mẫu không dùng làm căn cứ trả lời; tự điền mẫu sẽ có ở bản sau."

## Tests (`tests/test_templates.py`, TestClient + auth on via the `test_auth` pattern; clean up rows/files)
1. admin uploads a DOCX made in the test with python-docx containing "Họ và tên: ……" and "{{ten_cong_ty}}" →
   201, placeholders detected, preview stored; duplicate → 409.
2. legal_basis with a real node id (e.g. `blld2019-d20`) accepted; unknown id → 422.
3. Search by an unaccented word finds it; kind filter works; archive hides it from the default list.
4. Permissions: user1 upload → 403; anonymous list → 401; user1 list → 403; admin list → 200.
5. `search_nodes` never returns template content (templates are not in `legal_node`).

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_templates.py tests/test_auth.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/templates_lib app/api/routes.py app/db/models.py tests/test_templates.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
