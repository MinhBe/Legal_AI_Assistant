# Contract LI4 — watched inbox folder for documents Minh downloads himself

Spec: gap item LI4. Minh downloads full texts with his own account (we never use his credentials) and drops them in a
folder; the system ingests them and links them to `/tin-moi` items. Builds on U9 (upload service), LI2/LI3 (intel
items, `IntelDoc`). Read `AGENTS.md` first. Do not commit. Never read `.env`/`keys/`. No new packages.

## Files you may create or edit (nothing else)
- `backend/app/intel/inbox.py` (new)
- `backend/app/intel/scheduler.py` (poll the inbox every 60 s in the existing daemon thread, inside the scan lock)
- `backend/app/intel/store.py`
- `backend/app/config.py` (`inbox_dir: str = "/inbox"`, `inbox_poll_s: int = 60`)
- `backend/app/api/routes.py` (`GET /api/intel/inbox` status, `POST /api/intel/inbox/scan` — review permission)
- `docker-compose.yml` (mount `./inbox:/inbox` read-write on the api service, with a comment)
- `.gitignore` (add `inbox/`)
- `backend/tests/test_inbox.py` (new)
- `frontend/app/tin-moi/page.tsx`, `frontend/app/globals.css` (only `.intel-*`)

## Behaviour (`inbox.py`)
- `scan_inbox(db, root) -> dict`: for each file directly in `root` with extension `.pdf .docx .doc .txt` (ignore
  others and hidden/partial files: names starting with `.` or `~$`, or files modified < 10 s ago — still being
  written):
  1. `number = number_from_name(filename)` — recognise "399-2026-ND-CP", "399_2026_NĐ-CP", "NĐ 399/2026", "Nghi dinh
     399 2026" (normalise to `399/2026/NĐ-CP`); if none, after ingest look for the number in the first 2 000
     characters of the extracted text (`service.full_text`).
  2. Ingest with `upload_service.save_upload(db, data, filename, title=…)` (title = the matched intel item title, or
     the file stem) → pending review. Duplicate sha → reuse the existing upload.
  3. Match: intel items with the same normalised number (`IntelItem.number`, compare case/diacritics-insensitively);
     for each, write/replace the `IntelDoc` with `status="ingested"`, `source_url="inbox:<filename>"`,
     `upload_id`, and mark the item for re-analysis (status `new` so the next scan analyses it with full text).
  4. Move the file to `root/done/<YYYY-MM-DD>/<filename>` (create dirs; on name clash append `-1`, `-2`); on
     ingest failure move to `root/failed/` and write `<filename>.error.txt` with the reason.
  Returns counts `{ingested, matched, failed, skipped}`. Never raises.
- Scheduler: every `inbox_poll_s` seconds when `intel_enabled` (tests keep it off via conftest).

## API / UI
- `GET /api/intel/inbox` → `{dir, pending_files, last_scan_at, last_counts, recent: [{filename, number, upload_id,
  matched_item_ids, moved_to, at}]}` (keep the last 50 results in memory).
- `/tin-moi`: a small panel "Thư mục inbox" with the folder path as seen on Windows (`RAG\inbox`), pending count,
  last results, and a "Quét inbox ngay" button.

## Tests (`tests/test_inbox.py`, tmp dirs, sample files from `data/samples/upload/`, DB; clean up uploads/rows)
1. `number_from_name` table (the formats above + none).
2. A PDF named `399-2026-ND-CP.pdf` with an intel item numbered `399/2026/NĐ-CP` → upload pending_review, IntelDoc
   ingested with `inbox:` source, item status reset to `new`, file moved under `done/<date>/`.
3. A file without a number in the name but with "Nghị định số 145/2020/NĐ-CP" in its text → matched by content.
4. Unsupported extension skipped (left in place); a corrupt PDF → `failed/` + `.error.txt`; partial/hidden files
   ignored; never raises.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_inbox.py tests/test_intel_official.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/intel app/api/routes.py app/config.py tests/test_inbox.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
