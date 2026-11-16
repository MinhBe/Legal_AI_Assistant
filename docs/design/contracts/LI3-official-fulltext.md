# Contract LI3 — official full text by document number + full anle precedent catalogue

Spec: gap item LI3 (add rows LI3, LI4, TPL1 under "Added 2026-11-16" in `docs/design/v1.1-gap.md`, see the bottom
of this file for their text). Builds on LI1/LI2 (`app/intel/*`). Read `AGENTS.md` first. Do not commit. Never
read `.env`/`keys/`. No new packages; Playwright + `/usr/bin/chromium`, headless, `--disable-gpu`.

**Hard rule:** discovery sources (thuvienphapluat, luatvietnam, vanban.chinhphu) are never used for full text
beyond what LI2 already does; no cookies, no logins, no credential storage, no bot-block bypass, ever.

Facts verified by Claude on 2026-11-16:
- **congbao.chinhphu.vn** (robots `Allow: /`): the home page lists newly published documents; each has a page
  `https://congbao.chinhphu.vn/van-ban/<slug>-<id>.htm` with download links on `https://g7.cdnchinhphu.vn/api/
  download/stream?Url=…` whose link TEXT is the file name, e.g. `2026_576_399/2026/NĐ-CP.docx` and `…pdf`, and a
  "Hiệu lực: 01/01/2027" line. The site has a keyword search box (`input[name=keyword]`). g7.cdnchinhphu.vn uses the
  GlobalSign intermediate already in `app/intel/certs/` (the shared SSL context works). NĐ 399/2026 was fetched this
  way (DOCX, 69 713 bytes) and is ingested.
- **vbpl.vn**: robots `Disallow: /api/` and `/Pages/`; its search redirected to the home page → do NOT implement
  search there (leave a stub adapter with status `robots_disallow`).
- **anle.toaan.gov.vn** precedent list: `https://anle.toaan.gov.vn/webcenter/portal/anle/anle?selectedPage=<n>&
  docType=AnLe` (GET paging; 20 per page; "Tổng số Án lệ đã công bố: 90 án lệ"); fixture
  `data/fixtures/legal-intel/2026-11-16/anle_list_page1.html` (40 links = number link + title link per precedent).
  Use `wait_until="domcontentloaded"` + `wait_for_timeout(8000)` (networkidle times out on this site). Full text:
  `ShowProperty?nodeId=/UCMServer/<dDocName>` (robots 404 = allowed, already handled).

## Files you may create or edit (nothing else)
- `backend/app/intel/official.py` (new: congbao lookup + download by number), `backend/app/intel/precedents.py`
  (new: anle catalogue), `backend/app/intel/licensed.py` (new: interface only)
- `backend/app/intel/sources.py`, `backend/app/intel/fulltext.py`, `backend/app/intel/scheduler.py`,
  `backend/app/intel/store.py`
- `backend/app/db/models.py` (add `PrecedentCatalog` only)
- `backend/app/config.py` (`intel_catalog_interval_days: float = 7`, `licensed_api_provider: str = ""`,
  `licensed_api_base_url: str = ""`, `licensed_api_key_env: str = "LEGAL_DATA_API_KEY"`)
- `backend/app/api/routes.py` (`/api/intel/*` only)
- `backend/tests/test_intel_official.py` (new; fixtures + mocks, no network/browser)
- `frontend/app/tin-moi/page.tsx`, `frontend/app/globals.css` (only `.intel-*`)
- `docs/design/v1.1-gap.md`

## 1. Official full text by number (`official.py`)
- `congbao_lookup(number, render) -> {page_url, files: [{name, url, ext}], effective_date} | None`: render the
  congbao home page and, if the number is not there, submit the keyword search with the number and read the first
  result whose title contains the number; open its page; collect download links whose text contains the number;
  parse "Hiệu lực: dd/mm/yyyy". Prefer `.docx`, then `.pdf`.
- Pipeline in `fulltext.scan`: for an item with priority ≥ 1 and no ingested `IntelDoc`, try in order:
  anle file (precedents) → vanban.chinhphu PDF from the same run → `congbao_lookup(item.number)`. Record which
  source supplied the text (`IntelDoc.source_url`) and store `effective_date` from congbao in the analysis context.
- Use the shared `Fetcher` for downloads (robots, delay ≥ 5 s, size cap, SSL context). At most 5 congbao lookups
  per scan.

## 2. anle precedent catalogue (`precedents.py`)
- `PrecedentCatalog` (`precedent_catalog`): `doc_key` str(32) PK (dDocName), `number` (e.g. "90/2026/AL"), `title`,
  `url`, `file_url`, `status` str(16) (`dang_ap_dung` | `bi_huy_bo` | `chua_ro`), `status_note` text, `first_seen`,
  `last_checked`, `upload_id` null.
- `crawl(render, fetcher, db, max_pages=10)`: page 1..n of the list (stop when a page adds nothing new or n >
  max_pages), 5 s apart; parse number + title + dDocName (number link and title link share the dDocName); upsert.
- Status: open each NEW precedent's detail page once; if the page text mentions "bãi bỏ", "hủy bỏ", "không còn áp
  dụng" or "hết hiệu lực" near "án lệ" → `bi_huy_bo` with the sentence as `status_note`; else `dang_ap_dung`.
- Full text: for every precedent without `upload_id`, download the file (max 10 per crawl run, 5 s apart) and
  ingest with `save_upload` (title "Án lệ <number>: <title>"), pending review. Labour precedents (labour keywords in
  the title, `sources.labor_hint`) first.
- Scheduler: run the catalogue crawl every `intel_catalog_interval_days` (default 7) in the same scan lock; manual
  `POST /api/intel/precedents/crawl` (review permission). `GET /api/intel/precedents` → list with status + upload
  link.

## 3. Licensed data API slot (`licensed.py`) — interface only, OFF by default
`class LicensedSource(Protocol)`: `search(number) -> list[dict]`, `fetch(doc_id) -> bytes`. `get_licensed() ->
LicensedSource | None`: returns None unless `licensed_api_provider` is set AND the env var named by
`licensed_api_key_env` has a value (read with `os.getenv`, never logged). No provider implementation. Document in a
docstring that this is for a paid enterprise API of thuvienphapluat/luatvietnam if Minh buys one.

## 4. UI `/tin-moi`
- Item card: full-text line shows the source ("Toàn văn: Công báo — chờ duyệt", "Án lệ — chờ duyệt", "Không tìm
  thấy ở nguồn công khai — cần lấy tay") with a link to the source page.
- New tab "Án lệ (anle.toaan.gov.vn)": catalogue table (number, title, status badge Đang áp dụng / Bị hủy bỏ /
  Chưa rõ, full text link, last checked), a "Quét danh mục án lệ" button.

## Tests (`tests/test_intel_official.py`)
1. congbao parsing on a small fixture you create from the facts above (home list with the 399 entry + a detail page
   with the two download links and "Hiệu lực: 01/01/2027") → DOCX preferred, effective date parsed.
2. Pipeline order: anle item uses the anle file; a decree found in the vanban.chinhphu list uses that PDF; otherwise
   congbao; nothing found → status `not_found`, not an exception; congbao lookups capped at 5.
3. Catalogue: `anle_list_page1.html` → 20 precedents with number, title, dDocName; paging stops when a page adds
   nothing new; status detection on two tiny detail fixtures (one "đã bị bãi bỏ", one normal).
4. `get_licensed()` is None by default and when the key env var is empty; never reads `keys/`.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_intel_official.py tests/test_intel_v2.py tests/test_intel.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/intel app/api/routes.py app/config.py app/db/models.py tests/test_intel_official.py
docker compose exec -T web npx tsc --noEmit
```

## Gap rows to add
- LI3: official full text by number from congbao.chinhphu.vn (+ anle files); full anle precedent catalogue with
  status; vbpl.vn skipped (robots disallows search); licensed API slot off by default.
- LI4: watched inbox folder `RAG\inbox` → auto-ingest pending review, match to /tin-moi items by number.
- TPL1: templates (biểu mẫu) as a separate upload type with metadata, admin/dev only, not part of legal retrieval;
  auto-fill later (asked Minh).

Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
