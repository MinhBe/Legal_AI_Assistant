# Contract KG1 — fine-tuning kit for Kaggle (dataset builder, QLoRA notebook, GGUF export, eval)

Spec: gap item KG1 (add the row under "Added 2026-11-16" in `docs/design/v1.1-gap.md`). Minh has 30 GPU-hours a week
on Kaggle (2× T4, 15 GB each, 12 h per session, 57 GB disk). Goal: a small model that "speaks like a Vietnamese labour
lawyer" while RAG + Verifier keep citations exact. Read `AGENTS.md` first. Do not commit. Never read `.env`/`keys/`.
No new packages in the app image (the notebook installs its own packages on Kaggle).

## Files you may create or edit (nothing else)
- `backend/app/finetune/__init__.py`, `build.py`, `generate.py`, `filters.py` (new)
- `backend/scripts/ft_build.py` (new CLI), `backend/scripts/ft_eval.py` (new CLI)
- `finetune/README.md`, `finetune/kaggle_qlora.ipynb` (new folder at the repo root; the notebook is JSON — keep it
  small and readable; put long code in a single `.py` cell file `finetune/train.py` that the notebook `%run`s)
- `finetune/train.py`, `finetune/export_gguf.py` (new)
- `.gitignore` (add `finetune/out/` and `data/finetune/`)
- `backend/tests/test_finetune.py` (new)
- `docs/design/v1.1-gap.md`

## 1. Data (PUBLIC sources only — no uploads of class A/B, no answer records with client text)
`build.py`:
- `law_records(db)`: one record per article/clause of the real laws in `legal_document` (doc_type not `upload`:
  BLLĐ 2012, BLLĐ 2019, NĐ 145/2020, and NĐ 399/2026 once it is approved into the corpus), with `doc_id`, node_id,
  text, `valid_from`/`valid_to` from `provision_version`, and a time tag string, e.g. "BLLĐ 2019 (hiệu lực từ
  01/01/2021)" / "BLLĐ 2012 (hết hiệu lực từ 01/01/2021)".
- `precedent_records(db)`: the 90 anle precedents from `precedent_catalog` (+ full text when an approved upload
  exists).
- `approved_problem_records(db)`: `case_problem` rows with status `da_duyet` only (lawyer-approved, masked).
- Hold-out (no test leakage): keep all law records, but drop any generated question whose cosine similarity to a
  golden question (`backend/eval/golden_v2.jsonl`, embedded with `app.rag.embeddings.embed`) is ≥ 0.85.

`generate.py` (Dahl, public data → class C, cloud_first):
- For a law record: ask for N scenario Q&A pairs (default 3): a realistic question by a worker or employer, and an
  answer in Vietnamese that cites the article as "Điều X khoản Y {document} ({time tag})", plus 1 "time trap" pair
  for BLLĐ 2012/2019 differences where applicable. Strict JSON, pydantic-validated, one retry.
- For a precedent: summary, legal situation, holding, and 1–2 Q&A that cite "Án lệ số …".
- `--dry-run` prints the number of Dahl calls and an estimated token count for the chosen scope WITHOUT calling.
`filters.py` (code, no LLM): keep a pair only if (a) every cited "Điều X … {document}" exists in `legal_node` for
that document, (b) the time tag matches the document's validity, (c) answer has Vietnamese diacritics ratio ≥ 0.05,
(d) length limits (question 20–600 chars, answer 80–2 500), (e) not near-duplicate (cosine ≥ 0.95) of a kept pair.
Output `data/finetune/<run>/{train,val}.jsonl` in chat format `{"messages": [{"role": "system", …}, {"role":
"user", …}, {"role": "assistant", …}]}` with a fixed short system prompt; 95/5 split; and `manifest.json` (sources,
counts, filter rejects by reason, Dahl calls, git commit).

CLI: `python -m scripts.ft_build --scope pilot|laws|precedents|all --pairs 3 [--dry-run] [--max-calls 60]
--out data/finetune/<name>`; `--scope pilot` = 20 random law records + 5 precedents (target ≈ 50 pairs).

## 2. Notebook / training (`finetune/train.py`, run on Kaggle)
- Unsloth + Qwen2.5-7B-Instruct, 4-bit QLoRA (r=16, alpha=16, dropout 0, target all linear), max_seq_len 2048,
  batch 2 × grad-accum 4, lr 2e-4, 2 epochs, bf16 off / fp16 on (T4), gradient checkpointing "unsloth".
- Checkpoint every N steps (default 200) to `/kaggle/working/ckpt`, keep last 2; `--resume` picks the latest; a
  12-hour guard stops cleanly at 11 h 15 min after saving.
- Config at the top (model name, data path, steps) so Minh only edits one cell; README explains: upload
  `train.jsonl`/`val.jsonl` as a Kaggle dataset, enable GPU T4 ×2, Internet on, run all; how to resume.
- `export_gguf.py`: merge LoRA → save 16-bit → convert to GGUF Q4_K_M (Unsloth `save_pretrained_gguf`), write a
  Modelfile with `PARAMETER num_ctx 8192`, and print the `ollama create lawvn-qwen7b-ft -f Modelfile` command.

## 3. Eval (`scripts/ft_eval.py`, runs in the api container against Ollama)
`--model qwen2.5:7b --model lawvn-qwen7b-ft --limit N`: for golden rows with expected provisions, run the normal
`answer_with_citations` pipeline with `LOCAL_MODEL` overridden per run, and report per model: citation hit rate,
wrong-version citations, JSON validity, Verifier problems, avg latency. Writes `data/finetune/eval-<date>.json`.
Gate: the fine-tuned model may replace the current one only if citation hit rate is not lower and wrong-version
count is not higher.

## Tests (`tests/test_finetune.py`, no network, no LLM, no GPU)
1. `law_records` time tags correct for a 2012 and a 2019 node.
2. Filters: invented article rejected; wrong time tag rejected; near-duplicate rejected; good pair kept.
3. Golden leakage: a generated question equal to a golden question is dropped.
4. `--dry-run` computes call counts without calling the router (fake router asserts not called).
5. Output files are valid chat-format JSONL; manifest counts add up.
6. `train.py` and `export_gguf.py` at least import-check / `python -m py_compile` (they need GPU packages, so do not
   import unsloth at module import time — import inside `main()`).

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_finetune.py
docker compose exec -T api python -m scripts.ft_build --scope pilot --dry-run --out data/finetune/pilot
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/finetune scripts/ft_build.py scripts/ft_eval.py tests/test_finetune.py
docker compose exec -T api python -m py_compile /app/../finetune/train.py 2>/dev/null || python -m py_compile finetune/train.py
```
(The last line: compile-check from wherever the repo root is reachable; if `finetune/` is not mounted in the
container, run `python -m py_compile finetune/train.py finetune/export_gguf.py` on the host.)
Do NOT run the real generation (Claude runs the 50-pair pilot after review). Max 2 fix attempts per failure, then stop
and report. Finish with a 5-line summary.
