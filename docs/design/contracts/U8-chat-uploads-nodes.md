# Contract U8 — chat can use approved uploads (local only) + per-file node list

Spec: `docs/design/upload-ocr-kg-plan.md` (follow-ups), `docs/design/LawVN-v1.1.md` §4 (class A never leaves the
machine). Read `AGENTS.md` first. Do not commit. Never read `.env`. No new packages.

## Files you may create or edit (nothing else)
- `backend/app/api/routes.py` (`ChatRequest.use_uploads`, pass-through, new nodes endpoint)
- `backend/app/agent/pipeline.py` (pass `use_uploads` through `run_chat` → `_chat` → `answer_with_citations`)
- `backend/app/agent/qa.py`
- `backend/tests/test_chat_uploads.py` (new)
- `frontend/lib/chat/useChat.ts`, `frontend/components/chat/Composer.tsx` (toggle), `frontend/app/upload/page.tsx`,
  `frontend/app/globals.css` (only new `.up-nodes*` / `.use-uploads*` rules)

## Chat with approved uploads
- `ChatRequest.use_uploads: bool = False`; `run_chat(message, history, mode, use_uploads=False)` and on down to
  `answer_with_citations(message, history, use_uploads=False)`.
- When `use_uploads` is true, retrieval calls `search_nodes(..., include_uploads=True)` (only approved uploads are
  returned by `search_nodes`; do not change `rag/search.py`).
- **Privacy rule:** if any retrieved hit belongs to a document with `doc_type = 'upload'`, everything after
  retrieval that sends text to an LLM (answer generation, rewrite) must run with data class **A**: wrap those calls
  in `data_class_scope("A")` *before* submitting to the pool, so the router plans local only and raises
  `LocalModelUnavailable` when Ollama is down. The classifier call submitted before retrieval only sees the user's
  (already masked) message and may stay as is. Log `"Dùng tài liệu tải lên: {n} đoạn, mức A"`.
- Hits from uploads are shown like other citations; their `display` must start with "Tài liệu tải lên: {title}".
- The SSE `done` payload gets `"uses_uploads": true|false`.

## Per-file node list
- `GET /api/uploads/{upload_id}/nodes` → `{"upload_id", "doc_id", "nodes": [{node_id, level, heading, preview
  (first 200 chars of text), refs: [to_id…]}]}` ordered by `seq`; 404 when the upload is unknown.

## Frontend
- Composer: a checkbox/toggle "Dùng tài liệu đã duyệt (chỉ xử lý trong máy)"; when on, `useChat` sends
  `use_uploads: true`. Keep it off by default; remember it in component state only.
- When the AI message's `done` has `uses_uploads`, show a small chip "Có dùng tài liệu tải lên — xử lý trong máy".
- Upload page: each row gets a "Xem node" button that lazy-loads `/api/uploads/{id}/nodes` and shows a compact
  list (level, heading, preview, refs as chips). Follow the existing full-text toggle pattern.

## Tests (`tests/test_chat_uploads.py`, fakes only, no network)
1. With `use_uploads=True` and a fake search returning one upload hit (doc_type upload) + one law hit: the answer
   generation runs with `get_data_class() == "A"` (record it inside a fake router), the fake cloud provider is
   never called, `done` has `uses_uploads: True`.
2. With `use_uploads=False`: `search_nodes` is called with `include_uploads=False` (or without the flag), data class
   stays as the gateway set it.
3. Ollama down + upload hit → the user gets the "mô hình chạy trong máy" message (category `local_unavailable`).
4. `GET /api/uploads/{id}/nodes`: 404 for unknown id; for an ingested sample (reuse the fixtures in
   `tests/test_upload_api.py`) returns nodes with `preview` ≤ 200 chars.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_chat_uploads.py tests/test_upload_api.py tests/test_llm_tiers.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/api/routes.py app/agent/pipeline.py app/agent/qa.py tests/test_chat_uploads.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
