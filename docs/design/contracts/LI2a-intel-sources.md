# Contract LI2a — intel feed v2: anle via Playwright, official full text, 6-hour cadence, watchlist

Spec: gap item LI2 (add one row under "Added 2026-11-16" in `docs/design/v1.1-gap.md`). Minh: "chủ động cập nhật
như 1 threat intelligent … hạn chế tranh GPU". Builds on LI1 (`app/intel/*`, `/tin-moi`). Read `AGENTS.md` first.
Do not commit. Never read `.env`/`keys/`. No new packages: Playwright 1.49.1 + Debian `chromium` are already in the
image (`PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium`). Headless, `--disable-gpu` always (GPU is for Ollama).

Facts verified by Claude on 2026-11-16 (fixtures in `data/fixtures/legal-intel/2026-11-16/`):
- **TLS**: anle.toaan.gov.vn sends no intermediate certificate. The GlobalSign intermediate is committed at
  `backend/app/intel/certs/globalsign-rsa-ov-ssl-ca-2018.pem` (verified to chain to GlobalSign Root R3). Build ONE
  `ssl.SSLContext` = certifi bundle + every `*.pem` in that folder and use it for every httpx request. Never disable
  verification. For Playwright use the browser's own store (Chromium fetches intermediates via AIA).
- **anle.toaan.gov.vn** (no robots.txt → allowed): rendered home `/webcenter/portal/anle/home` lists "ÁN LỆ MỚI"
  (`chitietanle?dDocName=TAND…`, text like "84/2026/AL: Về …"), "DỰ THẢO ÁN LỆ MỚI" (`chitietanleduthao?dDocName=…`)
  and "NGUỒN ÁN LỆ" (`chitietnguonanle?dDocName=…`, "Bản án số …"). Fixture `anle_rendered_home.html`. Public full
  text (PDF) of a precedent: `https://anle.toaan.gov.vn/webcenter/ShowProperty?nodeId=/UCMServer/<dDocName>`.
- **vanban.chinhphu.vn** (robots `Allow: /`): the home page table lists new documents with number, date, summary
  and a public PDF link on `https://datafiles.chinhphu.vn/cpp/files/vbpq/...pdf` (fixture `vbcp_home_rows.html`).
  Its search (`/?pageid=473&q=…`) returned 0 results for numbers; paging the grid did not change the rows → only
  page 1 is reliable; the 6-hour cadence catches new documents while they are on page 1.
- **congbao.chinhphu.vn**: robots `Allow: /`; not explored — implement only if a simple listing with public files is
  found in one rendered page; otherwise leave a stub adapter returning `[]` with status `not_implemented`.
- thuvienphapluat document pages answer 403 to bots; luatvietnam is listing-only. Never bypass.

## Files you may create or edit (nothing else)
- `backend/app/intel/fetch.py` (shared SSL context; a `render(url) -> html` helper using Playwright sync API with a
  module-level lock so only one browser runs at a time, closed after each scan; same robots/delay rules)
- `backend/app/intel/sources.py` (new adapters `AnLe` (replace the stub), `VanBanChinhPhu`, `CongBao`)
- `backend/app/intel/fulltext.py` (new), `backend/app/intel/watchlist.py` (new)
- `backend/app/intel/store.py`, `backend/app/intel/analyze.py`, `backend/app/intel/scheduler.py`
- `backend/app/db/models.py` (add `IntelDoc` only — do not alter `IntelItem`/`IntelRun` columns)
- `backend/app/config.py` (`intel_interval_hours: float = 6`, `intel_fulltext: bool = True`,
  `intel_fulltext_max_mb: int = 30`)
- `backend/app/api/routes.py` (only `/api/intel/*`)
- `backend/tests/test_intel_v2.py` (new; fixtures + mocked fetch/render, no network, no browser)
- `frontend/app/tin-moi/page.tsx`, `frontend/app/globals.css` (only `.intel-*`)
- `docs/design/v1.1-gap.md` (one LI2 row)

## Behaviour
1. **Cadence**: scheduler runs a scan every `intel_interval_hours` (default 6) instead of once a day; manual
   "Quét ngay" unchanged. Never two scans at once.
2. **Adapters**: `AnLe.parse(rendered_html)` → items of kind `Án lệ` / `Dự thảo án lệ` / `Nguồn án lệ` with
   number (`84/2026/AL`, `DỰ THẢO … 42/2026`, `143/2025/DS-PT`), title, url, `doc_key` = dDocName.
   `VanBanChinhPhu.parse(html)` → items with number, issued date, summary, `pdf_url`. Both use `render()` live;
   tests feed fixture HTML directly to `parse`.
3. **Watchlist** (`watchlist.py`): `PRIORITY_TERMS` (lương tối thiểu, tiền lương, bảo hiểm xã hội, BHXH, bảo hiểm thất
   nghiệp, việc làm, Bộ luật Lao động, BLLĐ, hợp đồng lao động, an toàn vệ sinh lao động, công đoàn, kỷ luật lao động,
   thời giờ làm việc, nghỉ ngơi, trợ cấp) + every `legal_document.number` in the corpus (e.g. "145/2020/NĐ-CP") and
   doc ids' base numbers. `priority(item) -> 0..3`: 3 = title says it amends/replaces/guides a corpus document
   ("sửa đổi", "thay thế", "hướng dẫn", "bãi bỏ" + a corpus number); 2 = priority term; 1 = labour hint;
   0 = other. Store it (`IntelItem.labor_hint` stays as is; put priority in the analysis JSON or in `IntelDoc`).
   Analysis order = priority desc, then newest; the per-run cap stays 10.
4. **Full text** (`fulltext.py`), only for priority ≥ 1 and only from official public sources:
   - anle items → the `ShowProperty?nodeId=/UCMServer/<dDocName>` file;
   - any item (from any source) whose number appears in the `VanBanChinhPhu` listing of the same run → that
     `pdf_url`.
   Download with the shared fetcher (robots, delay, size ≤ `intel_fulltext_max_mb`, content-type pdf/doc/docx),
   store in `IntelDoc` (`intel_doc`: `item_id` PK, `source_url`, `sha256`, `bytes`, `fetched_at`, `upload_id` null,
   `status` `fetched` | `ingested` | `failed` | `blocked`, `error`), then pass the bytes to
   `app.upload.service.save_upload(...)` (title = item title) so the document enters the normal pending-review
   upload flow (class A rules do NOT apply: public law text, but it stays pending until a lawyer approves). Record
   `upload_id`. 401/403/429 → `blocked`, never retried in the same run.
   When full text was ingested, `analyze` adds the first 6 000 characters of the extracted text to the model
   context and sets `needs_full_text=false` unless the model says otherwise.
5. **API/UI**: items expose `priority`, `fulltext` (status + upload link `/upload` + "Xem toàn văn"),
   `doc_key`. `/tin-moi`: priority badge (Ưu tiên cao / Theo dõi), a "Toàn văn: đã lấy từ vanban.chinhphu.vn — chờ
   duyệt" line with a link to `/upload`, or "Cần lấy tay" with the source link when blocked/not found; per-source
   chips now include anle and vanban.chinhphu; show "Quét tự động mỗi 6 giờ · lần tới HH:MM".

## Tests (`tests/test_intel_v2.py`, no network, no browser)
1. SSL context loads certifi + the committed GlobalSign PEM (assert the PEM subject contains "GlobalSign RSA OV SSL
   CA 2018"); every httpx client in `fetch.py` is created with that context (monkeypatch and assert).
2. `AnLe.parse(anle_rendered_home.html)` → ≥ 5 precedents incl. "84/2026/AL" with dDocName "TAND377305", ≥ 3 drafts,
   ≥ 3 nguồn án lệ; full-text URL built correctly.
3. `VanBanChinhPhu.parse(vbcp_home_rows.html)` → includes "410/2026/NĐ-CP" with a `datafiles.chinhphu.vn` pdf URL.
4. Watchlist: an item "Nghị định sửa đổi Nghị định 145/2020/NĐ-CP" → priority 3; "lương tối thiểu" → 2; non-labour → 0;
   analysis order follows priority.
5. Full text: mocked fetch returning a small PDF (generate with pypdfium2 or reuse `data/samples/upload/*.pdf`) →
   `IntelDoc` `ingested` with an `upload_id` and the upload is `pending_review`; 403 → `blocked`; oversize → `failed`.
6. Scheduler interval uses `intel_interval_hours` (monkeypatched clock); `INTEL_ENABLED=false` in conftest still
   prevents any thread in tests.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_intel_v2.py tests/test_intel.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/intel app/api/routes.py app/config.py app/db/models.py tests/test_intel_v2.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
