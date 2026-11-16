# Contract G4 — eval gate (no LLM, costs $0 to run)

Spec: `docs/design/LawVN-v1.1.md` §11.2–11.4, §15.7 (and gap item G4). Read `AGENTS.md` first. Do not commit.
Done before you: `app/eval/golden.py` + `eval/golden_v2.jsonl` (G3), `app/gateway/pii.py` (G1).

## Files you may create or edit (nothing else)
- `backend/app/eval/gate.py` (new), `backend/scripts/eval_gate.py` (new CLI)
- `backend/eval/gate_baseline.json` (new, written by `--update-baseline`)
- `backend/tests/test_eval_gate.py` (new)
- `docs/design/eval-gate.md` (new, ≤ 40 lines: what is measured, how to run, how to update the baseline)

## Metrics (all computed locally, no LLM calls)
Over `golden_v2.jsonl` rows (use every row, reviewed or not, but report the reviewed count next to every number):
- `recall@5`, `recall@8`, `mrr` — for rows with `expected_action == "answer"` and provisions: does
  `search_nodes(db, question, top_k=k, as_of=event_date or None)` return an expected node or a child of an expected
  article (same article prefix `doc-dN`)?
- `version_correct` — group 5 only: share of rows whose top-8 hits contain the expected provision of the version in
  force on `event_date` AND no hit from the other version of the same article. Hard gate when the group has ≥ 1 row.
- `injection_block` — group 3 rows whose note/source marks them as injection: share caught by
  `app.agent.guard.looks_like_injection` (pattern layer only). Hard gate: must not drop below baseline.
- `pii_leak` — a fixed fake-PII set (put 20 synthetic sentences in `gate.py`, mix of all G1 entity types): count of
  original PII values still present after `app.gateway.pii.mask`. Hard gate: must be 0.
- `upload_isolation` — `search_nodes` for 5 fixed queries never returns a node whose document has
  `doc_type = 'upload'` (default call). Hard gate: true.
Every metric is reported with `n` (number of cases) and the 3/n upper error bound when the error count is 0 (§11.3).

## Gate (`gate.py`)
`run_gate(db) -> dict` (metrics), `compare(current, baseline) -> list[str]` (failures): hard gates above; soft gates:
`recall@5`, `recall@8`, `mrr` must not fall more than 2 percentage points (0.02) below the baseline (§15.7).
CLI `python -m scripts.eval_gate` prints a table and exits 1 on any failure; `--update-baseline` writes
`eval/gate_baseline.json` (with date, git commit if available, n per metric); `--json` prints machine output.

## Tests (`tests/test_eval_gate.py`)
Pure: `compare` flags a 3-point recall drop, accepts a 1-point drop, flags `pii_leak > 0`, flags `upload_isolation` false.
DB (`@pytest.mark.db`): `run_gate` returns all metrics with `n > 0`; `pii_leak == 0`; `upload_isolation` is true.

## Done when
```
docker compose exec -T api python -m scripts.eval_gate --update-baseline
docker compose exec -T api python -m scripts.eval_gate            # exit 0
docker compose exec -T api python -m pytest -q tests/test_eval_gate.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/eval scripts/eval_gate.py tests/test_eval_gate.py
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary including the baseline numbers.
