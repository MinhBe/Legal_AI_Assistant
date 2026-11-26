# AGENTS.md — Legal Agentic (Vietnamese labor-law assistant)

Pointer file for coding agents. Keep it short and stable; details live in the docs below.

## What this is
RAG assistant for Vietnamese labor law: hybrid retrieval over law nodes (Điều/Khoản/Điểm) in
Postgres + pgvector, answers with citations, guard against off-topic/injection, human review of
out-of-corpus questions, time-travel lookup (`law_as_of`). User-facing text is Vietnamese.

## Where the target design lives
- Design v1.1 (the spec to implement): `docs/design/LawVN-v1.1.md` (sections 1–15); 7B/7C
  companion: `docs/design/7B-7C-khung-nhan-dien-dieu-tra.md` (out of scope for now).
- Work queue derived from it: `docs/design/v1.1-gap.md` (ordered by dependency; do items in order).
- Current-state docs: `README.md`, `docs/TONG-QUAN-DU-AN.md`, `docs/kiem-toan-va-ke-hoach-sua.md`,
  `docs/ket-qua-do-luong.md`.

## Code map (backend = FastAPI, `backend/app/`)
- API routes: `api/routes.py` (chat SSE, `law_as_of_route` ~:96, draft, escalate ~:367, graph); entry `main.py`.
- Answer pipeline: `agent/qa.py` (retrieval → LLM → citations, issue split >60 words),
  `agent/pipeline.py`, `agent/guard.py` (injection patterns + LLM classify), `agent/followup.py`,
  `agent/precedent.py`.
- Retrieval: `rag/search.py` (hybrid vector + trigram/BM25), `rag/bm25.py`, `rag/embeddings.py`
  (self-hosted model), `rag/rerank.py`, `rag/text.py`.
- LLM: `llm/router.py` (`class LLMRouter` ~line 130: parallel race of Dahl models, Gemini/Claude fallback).
- Time model: `amend/store.py` (`law_as_of`, `node_supersession`), `amend/diff.py`.
- Schema: `db/models.py` (legal_document, legal_node, node_supersession, node_reference,
  document_relation, precedent, thread, message); SQL init `db/init/001_init.sql`.
- Ingestion: `ingestion/` (parser, ingest, references). Drafting: `draft/nd30.py`.
- Observability: `obs/lf.py` (Langfuse), `obs/metrics.py`. Prompts: `prompts/`.
- Eval: `backend/eval/gold_v1.jsonl` (50 model-written cases, not yet reviewed),
  `backend/scripts/eval_gold.py`, results in `backend/eval/results/`.
- Frontend: `frontend/` (Next.js 15: chat, `app/graph`, `app/dashboard`, `app/pv`).
- Data: `data/` (escalations, out_of_scope log, raw sources).

## Tests
- Run inside the api container (host Python lacks the deps):
  `docker compose exec api sh -c "pip install -q -r requirements-dev.txt && python -m pytest -q -m 'not llm'"`
- `@pytest.mark.db` tests skip when the DB is empty; `@pytest.mark.llm` tests need
  `RUN_LLM_TESTS=1` and spend real quota — never run them unless asked.
- Lint: `docker compose exec api ruff check .`

## Hard rules
- Never open, print, grep or copy `.env`, `.env.*` (except `.env.example`), `.dahl.env`, key files
  or tokens; never print a secret. Name variables only; scans report file/commit/rule, not values.
- Code decides dates and law versions; the LLM never infers effective dates (design §1, §5).
- Commit messages follow `.gitmessage` (Vietnamese, `type(scope): ...`, body sections
  Vì sao / Thay đổi / Kiểm chứng / Phạm vi). The `commit-msg` hook enforces it.
- One fix or feature per commit; tests pass before committing. No push, no force-push.
- Do not touch `sync2.bundle` or published images; security items in the gap list need Minh.
- Legal content changes (new law texts, effective dates, transition rules) need a lawyer's
  review; mark unverified legal facts `[cần đối chiếu]` instead of filling them from memory.
