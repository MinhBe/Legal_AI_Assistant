# Contract U3 — turn extracted text into graph nodes + keep uploads out of chat retrieval

Plan: `docs/design/upload-ocr-kg-plan.md` (steps U3 and the safety part of U5). Read `AGENTS.md` first. Do not commit.
U2 is done: `app/upload/extract.py` gives `Extraction(text, pages, ...)`.

## Files you may create or edit (nothing else)
- `backend/app/upload/ingest.py` (new)
- `backend/app/rag/search.py` (only the filter described below)
- `backend/tests/test_upload_ingest.py` (new)

## API (`app/upload/ingest.py`)
```python
SECTION_TARGET = 800      # chars per section node
SECTION_MAX = 1200        # a paragraph longer than this is split at sentence ends (". ", "; ", "\n")

def make_doc_id(sha256_hex: str) -> str: ...            # "up_" + first 10 hex chars
def split_sections(text: str) -> list[str]: ...         # paragraphs (blank-line separated) merged up to SECTION_TARGET
def build_rows(doc_id: str, title: str, text: str) -> tuple[str, list[dict]]: ...
def ingest_upload(db, *, doc_id: str, title: str, text: str, filename: str) -> dict: ...
def delete_upload(db, doc_id: str) -> None: ...          # deletes the legal_document row (nodes and references cascade)
```

## Behaviour
- `build_rows`:
  1. Try the law parser: `parse_articles(text)`, `assign_ids(doc_id, articles)`, `errors = validate(articles, text)`
     (from `app.ingestion.parser`). If there is at least 1 article and `errors` is empty → mode `"articles"`, rows from
     `app.ingestion.ingest._nodes_from_articles(doc_id, articles, None, None)` (keeps the `_ctx` key for embedding).
  2. Otherwise mode `"sections"`: one row per chunk from `split_sections`: `node_id=f"{doc_id}-s{i}"` (i from 1),
     `level="section"`, `heading` = first line of the chunk cut to 80 chars, `text` = chunk, `seq=i`, `parent_id=None`,
     article/clause/point fields None, `_ctx = f"{title}: {chunk}"`.
  Return `(mode, rows)`. Empty text → `ValueError("no text")`.
- `ingest_upload`: idempotent (calls `delete_upload` first). Adds
  `LegalDocument(doc_id, title, doc_type="upload", status="pending_review", source_url=f"upload://{filename}")`, then the
  rows with `text_hash` (sha256 first 16 hex of the text) and `embedding` from `app.rag.embeddings.embed([r["_ctx"] ...])`.
  Then references: for every row run `app.ingestion.references.extract_refs(row["text"], doc_id, article_context=<text of
  its article row, or None>)`; keep targets that exist in `legal_node` and are not the row itself; insert one
  `NodeReference(from_id, to_id, ref_text)` per distinct pair. Commit once. Return
  `{"doc_id", "parse_mode", "n_nodes", "n_refs", "ref_targets": sorted distinct target node_ids}`.
- No LLM calls, no network. Uploaded data is class A (design §4, §8).

## Safety filter (`app/rag/search.py`)
`search_nodes(..., include_uploads: bool = False)`: extend the existing `eff_clause` so that
- by default every node whose document has `doc_type = 'upload'` is excluded;
- with `include_uploads=True`, only uploads with `status = 'approved'` are allowed.
Use a SQL fragment such as `AND doc_id NOT IN (SELECT doc_id FROM legal_document WHERE doc_type = 'upload' ...)`; it must
apply to the vector, bm25 and hybrid paths (they all use `eff_clause`/`_allowed_ids`). Existing callers stay unchanged, so
chat never cites a pending upload.

## Tests (`backend/tests/test_upload_ingest.py`)
Pure tests (no DB): `make_doc_id`; `split_sections` merges short paragraphs, never returns a chunk > SECTION_MAX, keeps all
text; `build_rows` on the text of `data/samples/upload/noi-quy-lao-dong.pdf` (via `extract`) → mode `articles` with
`up_x-d3` present; on the text of `hop-dong-lao-dong-mau.docx` → whichever mode, ≥ 3 rows, ids unique.
DB tests (`@pytest.mark.db`, skip when `legal_node` is empty, like the existing db tests in `tests/`): ingest the PDF sample
under doc_id `up_testu3pdf` → `n_refs ≥ 3` and `ref_targets` contains `blld2019-d125`; `search_nodes(db, "sa thải nội quy
Công ty Mẫu An Bình", top_k=20)` returns no node with doc_id starting `up_`; after setting the document status to `approved`,
the same search with `include_uploads=True` may return it; finally `delete_upload` leaves no row with that doc_id. Always
clean up in a `finally`.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_upload_ingest.py tests/test_upload_extract.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/upload app/rag/search.py tests/test_upload_ingest.py
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
