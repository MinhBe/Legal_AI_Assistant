# Contract G2 — tiered router by data level (replace the parallel LLM race)

Spec: `docs/design/LawVN-v1.1.md` §2.2, §3 (model tiers, escalation), §4 (class → allowed providers); gap item G2.
Minh's choice (2026-11-16): **A and B → local model only** (Ollama, OpenAI-compatible); **C → local first, escalate to
DeepSeek API**. Read `AGENTS.md` first. Do not commit. Never read or print `.env` values (use variable NAMES only).

## Files you may create or edit (nothing else)
- `backend/app/config.py` (new settings), `backend/app/llm/router.py`, `backend/app/llm/context.py` (new)
- `backend/app/agent/pipeline.py` (set the data level for the request; friendly message when local is unavailable)
- `.env.example` (add the new variable names with empty/default values and one comment line each)
- `backend/tests/test_llm_tiers.py` (new); `backend/tests/test_llm_router.py` (update only tests that assert the old race
  is the default plan)

## Settings (`config.py`, all from env, names only)
`OLLAMA_BASE_URL` default `http://host.docker.internal:11434/v1`; `LOCAL_MODEL` default `qwen2.5:7b`;
`LOCAL_TIMEOUT` default 120 (s); `DEEPSEEK_BASE_URL` default `https://api.deepseek.com`; `DEEPSEEK_API_KEY` (no default);
`DEEPSEEK_MODEL` default `deepseek-flash`; `LLM_LEGACY_RACE` default false (true = old Dahl/Gemini/Claude/FPT plan, kept only
as an explicit opt-in; the race code stays but is unreachable by default).

## Data level per request (`llm/context.py`)
A `ContextVar[str]` `current_data_class` (default `"C"`), `data_class_scope(level)` context manager, `get_data_class()`.
`pipeline.run_chat` wraps the whole `_chat(...)` iteration in `data_class_scope(g.data_class)`. Make sure the value reaches
the worker threads that `qa.py` uses (`metrics.submit` already copies contextvars — verify; if not, pass the level
explicitly). Callers outside chat (reports, precedent synthesis) keep the default "C" (they only send law text).

## Router plan (`router.py`)
`_plan(task)` when `LLM_LEGACY_RACE` is false:
- A or B → `[("local", LOCAL_MODEL)]` only. Never an external provider, whatever the task.
- C → `[("local", LOCAL_MODEL), ("deepseek", DEEPSEEK_MODEL)]`, filtered by availability.
`available_providers()` → `{"local": <configured>, "deepseek": bool(DEEPSEEK_API_KEY)}` plus the legacy ones only when
`LLM_LEGACY_RACE` is true. "local" availability = a cached reachability probe (GET `<OLLAMA_BASE_URL>/models`, 2 s timeout,
cache 60 s) — no probe at import time.
Escalation: try the plan in order; move to the next entry on a provider error, a timeout, or when `parse` fails (this is
the "Verifier fails" signal for now); log `provider, model, data_class, escalated_from`. No parallel calls.
`stream()`: same plan; local and DeepSeek both stream through the OpenAI-compatible client; strip `<think>` blocks when a
model emits them (reuse `strip_think` on the full text for `chat`, and drop think content while streaming).
Errors: if the level is A or B and local is unavailable, raise `LocalModelUnavailable(LLMError)` with a Vietnamese message.
Record every call with `metrics` like the existing providers (provider names `local`, `deepseek`).

## Pipeline (`agent/pipeline.py`)
On `LocalModelUnavailable` yield one token: "Câu hỏi có thông tin cá nhân nên chỉ được xử lý bằng mô hình chạy trong máy,
nhưng mô hình này chưa sẵn sàng. Vui lòng thử lại sau hoặc bỏ thông tin cá nhân khỏi câu hỏi." then `done` with
`{"category": "local_unavailable"}`. The "no provider configured" message must name the new variables (names only).

## Tests (`tests/test_llm_tiers.py`, mocked, no network)
Monkeypatch the provider call functions to fakes that record (provider, model, messages):
1. Level B: only `local` is called; when local raises, `LocalModelUnavailable` is raised and DeepSeek is never called.
2. Level A: same as B.
3. Level C: local is tried first; when it fails (error or bad JSON with `parse`), DeepSeek is called once; when local
   succeeds DeepSeek is not called.
4. Default `LLM_LEGACY_RACE=false`: the plan for every task contains no `dahl`, `gemini`, `claude`, `fpt`.
5. `run_chat` with a message containing a fake phone number and a fake local that raises unavailable: the user receives the
   Vietnamese "mô hình chạy trong máy" message; the fake DeepSeek recorded nothing.
6. Contextvar propagation: a call made through `metrics.submit` inside `data_class_scope("B")` sees "B".

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_llm_tiers.py tests/test_llm_router.py
docker compose exec -T api python -m pytest -q -m "not llm"          # 251 passed baseline must stay green
docker compose exec -T api python -m scripts.eval_gate                # ĐẠT (no LLM)
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/llm app/config.py app/agent/pipeline.py tests/test_llm_tiers.py
bash scripts/e2e-upload.sh                                            # KẾT QUẢ: ĐẠT
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
