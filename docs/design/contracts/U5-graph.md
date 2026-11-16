# Contract U5 — graph view of one uploaded document

Plan: `docs/design/upload-ocr-kg-plan.md` (step U5). Read `AGENTS.md` and the module docstring of
`backend/app/graph/builder.py` (two-phase build: collect nodes first, then edges) first. Do not commit.
Done before you: uploads are stored as `legal_document(doc_type='upload')` + `legal_node` rows (levels article/clause/point,
or `section` for free text) + `node_reference` rows to law nodes; `search_nodes(..., include_uploads=False)` hides them.

## Files you may edit (nothing else)
- `backend/app/graph/builder.py`
- `backend/app/api/routes.py` (only `graph_route`)
- `backend/tests/test_upload_graph.py` (new)

## Changes
1. `build_graph(db, query, top_k, *, doc_id: str | None = None, include_uploads: bool = False)`.
   - `doc_id` given: seed = all `legal_node` rows of that document ordered by `seq` (limit `top_k`), shaped like search hits
     (`_display`, score 0). Then the normal phase 1/phase 2 pipeline, so reference targets in the law (ghost nodes) and
     their ancestry/document nodes appear with `references` edges.
   - `doc_id` not given: unchanged behaviour, except `_seed_hits` must never return upload nodes unless
     `include_uploads=True` (pass it to `search_nodes`; in the empty-query SQL path add the same upload exclusion).
2. Section nodes: label = `heading` (fallback node_id) + ` (` + document name + `)`; add a `contains` edge from
   `doc:<doc_id>` to every node of level `section` (in `_add_documents`, next to the chapter/article rule).
3. Every node gets `"upload": true` when its document has `doc_type = 'upload'` (one query per build), and document nodes of
   uploads carry `"status"` (pending_review / approved / rejected).
4. `doc_name()` caches titles; make sure a freshly uploaded document gets its title, not its id (the cache refreshes
   on unknown ids already — verify, do not rewrite it).
5. `graph_route`: add query params `doc_id: str | None = None` and `uploads: bool = False`, pass them through (law mode only).

## Tests (`tests/test_upload_graph.py`, `@pytest.mark.db`)
Use `app.upload.service.save_upload` with `data/samples/upload/noi-quy-lao-dong.pdf` (clean up with `remove_upload` in a
`finally`):
- `build_graph(db, "", 150, doc_id=<doc_id>)` → has `doc:<doc_id>` with `upload` true and `status` "pending_review"; has the
  node `blld2019-d125` (ghost allowed) and at least one edge of type `references` from an upload node to a `blld2019` node;
  every upload node is reachable from `doc:<doc_id>` through `contains` edges.
- Same with the DOCX sample (section mode if the parser rejects it): section nodes have a label that does not start with
  `up_` and a `contains` edge from the document node.
- `build_graph(db, "kỷ luật sa thải", 150)` (no doc_id) contains no node with `upload` true.
- API: `GET /api/graph?doc_id=<doc_id>` returns the same node ids as the direct call.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_upload_graph.py tests/test_upload_api.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/graph app/api/routes.py tests/test_upload_graph.py
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
