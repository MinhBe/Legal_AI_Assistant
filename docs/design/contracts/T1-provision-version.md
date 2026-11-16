# Contract T1 — provision_version, transition_rule, legal_link (time model tables + backfill)

Spec: `docs/design/LawVN-v1.1.md` §5.1; gap item T1. Read `AGENTS.md` first. Do not commit. Never read `.env`.
There is no migration tool: tables are created by `Base.metadata.create_all` at app start (`app/main.py`), so adding
models is enough. Existing tables and `amend/store.py:law_as_of` must keep working unchanged.

## Files you may create or edit (nothing else)
- `backend/app/db/models.py` (add three models at the end; do not change existing models)
- `backend/app/amend/versions.py` (new)
- `backend/scripts/backfill_versions.py` (new)
- `backend/tests/test_provision_version.py` (new)

## Models (`db/models.py`)
`ProvisionVersion` (`provision_version`): `id` int PK autoincrement; `provision_key` str(96) FK `legal_node.node_id`
ON DELETE CASCADE, indexed; `doc_id` str(64) indexed; `text_hash` str(64) nullable; `source_url` text nullable;
`valid_from` date nullable; `valid_to` date nullable (exclusive); `status` str(24) — one of
`in_force`, `partly_in_force`, `pending_amendment`, `not_yet_in_force`, `repealed`; `adopted_on` date nullable;
`amended_by` str(64) nullable (doc_id); `known_from` date not null; `known_to` date nullable.
Unique (`provision_key`, `valid_from`).
`TransitionRule` (`transition_rule`): `id` PK; `doc_key` str(64) (doc that contains the rule); `condition` text;
`outcome` str(16) — `old_law` | `new_law` | `mixed`; `provision_ref` str(96) nullable; `note` text nullable.
`LegalLink` (`legal_link`): `id` PK; `from_key` str(96); `to_key` str(96) (node_id or doc_id); `link_type` str(16) —
`guides` | `amends` | `replaces` | `cites` | `based_on`; `valid_from`, `valid_to` date nullable; `source` str(32)
(where the row came from: `node_reference`, `node_supersession`, `document_relation`, `seed`).
Unique (`from_key`, `to_key`, `link_type`).

## `amend/versions.py`
- `STATUSES` tuple of the five statuses above.
- `status_at(valid_from, valid_to, day) -> str`: `not_yet_in_force` if valid_from > day; `repealed` if valid_to and
  valid_to <= day; else `in_force`. Pure function.
- `backfill(db, *, today: date | None = None) -> dict[str, int]`: idempotent (delete rows with `source`/backfilled
  marker, or upsert — a second run must give identical counts).
  - One `provision_version` row per `legal_node` whose document `doc_type` is not `upload`: valid_from =
    `node.effective_from` or `document.effective_date`; valid_to = `node.effective_to` or `document.expired_date`;
    status = `status_at(valid_from, valid_to, today)`; text_hash = `node.text_hash`; source_url = document source_url;
    known_from = today; amended_by = doc_id of the replacing document for nodes with a `node_supersession` row.
  - `legal_link` rows: every `node_reference` → `cites`; every `node_supersession` (old→new) → `replaces` from new to
    old with valid_from = the new node's valid_from; every `document_relation` REPLACES → `replaces` (doc level).
  - Seed rows (source `seed`): `nd145_2020` → `blld2019` `guides` (valid_from 2021-02-01); one `transition_rule`:
    doc_key `blld2019`, condition "Hợp đồng lao động giao kết trước ngày 01/01/2021", outcome `mixed`,
    provision_ref = the node_id of BLLĐ 2019 Điều 220 if it exists (look it up by doc_id + article_no, level article),
    note "Điều 220 BLLĐ 2019: hợp đồng còn thời hạn tiếp tục thực hiện, trừ nội dung trái luật mới — cần đối chiếu".
  - Returns counts per table.
- `versions_for(db, provision_key) -> list[dict]` ordered by valid_from.
- `in_force_at(db, day: date, doc_id: str | None = None) -> list[str]`: provision_keys with
  valid_from <= day (or null) and (valid_to null or > day).
- `drop_tables(engine)`: drops the three tables (the "down migration").

## `scripts/backfill_versions.py`
`python -m scripts.backfill_versions` → create tables if missing, run `backfill`, print counts.
`--drop` → `drop_tables` and exit.

## Tests (`tests/test_provision_version.py`, mark the DB ones `@pytest.mark.db` like other DB tests)
1. `status_at` table test (before / inside / after / open ended).
2. After `backfill`: provision_version count == number of non-upload legal_node rows; every blld2012 row has
   valid_to 2021-01-01 and status `repealed` (today = 2026-11-16); blld2019 rows `in_force`.
3. Running `backfill` twice gives the same counts in all three tables.
4. `in_force_at(date(2020, 6, 1))` contains blld2012 keys and no blld2019 keys; `in_force_at(date(2022, 1, 1))` the
   opposite.
5. `legal_link` has the seed `guides` row and ≥ 1 `cites` row; `transition_rule` has the seed row.
6. `law_as_of` from `amend/store.py` still returns the same number of rows as before backfill.

## Done when
```
docker compose exec -T api python -m scripts.backfill_versions
docker compose exec -T api python -m pytest -q tests/test_provision_version.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/db/models.py app/amend/versions.py scripts/backfill_versions.py tests/test_provision_version.py
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary including the three table counts.
