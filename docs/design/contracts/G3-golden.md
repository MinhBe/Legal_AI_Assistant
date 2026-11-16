# Contract G3 — golden set v2: five groups, schema, migration of the 50 old cases

Spec: `docs/design/LawVN-v1.1.md` §11.1 (and gap item G3). Read `AGENTS.md` first. Do not commit. No LLM calls (you may
read the DB to ground expected node ids).

## Files you may create or edit (nothing else)
- `backend/eval/golden_v2.jsonl` (new), `backend/eval/golden_schema.md` (new, short)
- `backend/app/eval/__init__.py`, `backend/app/eval/golden.py` (new: load + validate)
- `backend/scripts/migrate_gold_v2.py` (new, one-off, idempotent)
- `backend/tests/test_golden_v2.py` (new)

## Schema (one JSON object per line)
`id` (e.g. "G1-001"), `group` (1 hoi_dap | 2 nhieu_van_de | 3 tu_choi | 4 chuyen_luat_su | 5 bay_thoi_gian — store the
int), `question`, `history` (list, may be empty), `event_date` (ISO or null), `advice_date` (ISO, default "2026-11-16"),
`facts` (dict, may be empty), `expected_action` ("answer" | "refuse" | "escalate"), `expected_provisions` (list of
`{"node_id": str, "doc_id": str}`; article-level ids allowed), `reviewed` (bool, false for everything you create),
`source` ("gold_v1:<old id>" or "synthetic:G3"), `note`.
`golden.py`: `load_golden(path=None) -> list[dict]`, `validate(rows, db=None) -> list[str]` (errors: duplicate ids, bad
group/action, bad dates, answer cases without provisions, and — when `db` is given — provision node_ids that do not exist
in `legal_node`), `group_counts(rows) -> dict[int, int]`, `TARGETS = {1: 30, 2: 20, 3: 20, 4: 20, 5: 30}`.

## Migration (`scripts/migrate_gold_v2.py`, writes golden_v2.jsonl; re-running gives the same file)
From `eval/gold_v1.jsonl` (50 rows; fields id/category/question/history/expect/expected_articles/
expected_articles_as_of/expected_nodes/as_of/reviewed/source/note): map categories → groups:
tra_cuu, nghi_dinh, noi_tiep → 1; nhieu_van_de → 2; ngoai_kho → 3 (expect "refuse"); thoi_diem → 5 (use `as_of` as
`event_date`, provisions from `expected_articles_as_of` when present). Keep `reviewed: false` (no human has reviewed).
Keep the known wrong label from the audit as is but put `"note": "audit E03: label likely wrong (BLLĐ 2019 ch. XIV covers
it), lawyer to review"` on old id E03.
Then add synthetic cases (all `reviewed: false`, `source: "synthetic:G3"`) grounded in the DB, no LLM:
- group 5 "time traps": at least 10, built from the BLLĐ 2012 → 2019 switch on 2021-01-01 that is in the corpus (both
  `blld2012` and `blld2019` exist; `app.amend.store.law_as_of` / `effective_from/to` tell which node applies). Pair cases
  with event dates before and after 2021-01-01 for the same question topic (e.g. retirement age, notice period, probation),
  expected provisions = the node of the version in force on `event_date` (verify with a DB query in the script).
- group 4 "needs a lawyer": at least 6 (dismissal of a union officer, near the limitation deadline, criminal-adjacent gift
  question, client in distress, case citing a draft decree, sanctions near 10/9/2026), expected_action "escalate".
- group 3: add at least 5 injection-style refusals (prompt injection in Vietnamese and mixed English), expected "refuse".
Print per-group counts vs `TARGETS` at the end (gaps are expected; lawyers fill them later).

## Tests (`tests/test_golden_v2.py`)
Pure: file loads; `validate(rows)` returns no errors; ids unique; every row `reviewed is False`; group 5 has ≥ 10 rows and
each has `event_date`; E03 carries the audit note. DB (`@pytest.mark.db`): `validate(rows, db)` returns no errors (all
provision node_ids exist); for each group-5 row the expected node's document is in force on `event_date`.

## Done when
```
docker compose exec -T api python -m scripts.migrate_gold_v2
docker compose exec -T api python -m pytest -q tests/test_golden_v2.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/eval scripts/migrate_gold_v2.py tests/test_golden_v2.py
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary including the per-group counts.
