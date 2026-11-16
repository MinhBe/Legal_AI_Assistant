# Contract LI1 — legal-intel feed: watch new documents/precedents, Dahl analysis, digest for lawyers

Spec: gap item LI1 (add a row to `docs/design/v1.1-gap.md` under "Added 2026-11-16"). Minh: "luồng chủ động lấy dữ
liệu như kiểu threat intelligence … cập nhật thông tin và bản tóm tắt cho các luật sư … dùng Dahl để suy luận và
điều hướng cực chi tiết". Read `AGENTS.md` first. Do not commit. Never read `.env` or `keys/`. No new packages
(use `httpx`, `urllib.robotparser`, `html.parser`, `pydantic` — all present).

Facts from the manual scan on 2026-11-16 (fixtures in `data/fixtures/legal-intel/2026-11-16/`):
- thuvienphapluat.vn: robots allows all; the home page lists new documents (anchors with category in the URL path,
  e.g. `/van-ban/Lao-dong-Tien-luong/...`); document pages answered **HTTP 403** to a bot → never retry, mark
  `blocked`, show "cần lấy tay".
- luatvietnam.vn: robots disallows `/tim-van-ban.html?Keywords=*` and search pages; `/van-ban-moi.html` lists new
  documents (relative links ending `-d1.html` / `-d2.html`).
- anle.toaan.gov.vn: an Oracle ADF JavaScript app — plain HTTP returns only a loader (fixture `anle_home.html`).
  Adapter returns status `needs_browser` with zero items (no Playwright: Minh has not approved installing it).

## Files you may create or edit (nothing else)
- `backend/app/intel/__init__.py`, `fetch.py`, `sources.py`, `store.py`, `analyze.py`, `scheduler.py` (new)
- `backend/app/db/models.py` (add `IntelItem`, `IntelRun` at the end)
- `backend/app/config.py` (`intel_enabled: bool = True`, `intel_daily_hour: int = 7`, `intel_delay_s: float = 5.0`,
  `intel_max_pages: int = 1`, `intel_user_agent: str = "Mozilla/5.0 (compatible; LegalNewsBot/0.1)"`)
- `backend/app/main.py` (start/stop the scheduler thread in the lifespan when `intel_enabled`)
- `backend/app/api/routes.py` (new `/api/intel/*` endpoints only)
- `backend/tests/test_intel.py` (new; fixtures only, no network)
- `docs/design/v1.1-gap.md` (one LI1 row)
- `frontend/app/tin-moi/page.tsx` (new), `frontend/components/chat/Sidebar.tsx` (one link "Tin pháp luật mới",
  shown only when `can("review")`), `frontend/app/globals.css` (only new `.intel-*` rules)

## Fetching (`intel/fetch.py`)
- `Fetcher(user_agent, delay_s)`: `httpx.Client(follow_redirects=True, timeout=30)`; per-host minimum delay
  `delay_s` between requests (sleep); robots.txt per host via `urllib.robotparser` (cached; when robots cannot be
  read, allow only the listing URLs configured in `sources.py`); `get(url) -> (status, text)`; never sends cookies,
  never logs in, never solves CAPTCHAs; 401/403/429 → status returned as is (caller marks `blocked`). Raw pages
  cached under `/app/data/cache/legal-intel/<date>/` (gitignored).

## Sources (`intel/sources.py`)
Each adapter: `name`, `listing_urls`, `parse(html, base_url) -> list[dict]` with keys `source, url (absolute),
title, number (e.g. "399/2026/NĐ-CP" or "11636/VPCP-KGVX"), kind (Nghị định / Thông tư / Quyết định / Công văn /
Kế hoạch / Văn bản hợp nhất / Luật / Nghị quyết / Án lệ / Dự thảo), category (from the URL path when present),
listed_date (if shown, else null)`. Deduplicate by URL. Parse with `html.parser`, not regex on the whole page.
- `ThuVienPhapLuat`: listing `https://thuvienphapluat.vn/`.
- `LuatVietnam`: listing `https://luatvietnam.vn/van-ban-moi.html`.
- `AnLe`: listing `https://anle.toaan.gov.vn/`; `parse` detects the ADF loader and returns `[]` with
  `adapter.last_status = "needs_browser"`.
- `labor_hint(item) -> bool`: keywords on title + category (lao động, tiền lương, việc làm, bảo hiểm xã hội, BHXH,
  bảo hiểm thất nghiệp, công đoàn, an toàn vệ sinh lao động, người lao động, viên chức, Lao-dong-Tien-luong,
  Bao-hiem, án lệ).

## Storage (`intel/store.py`)
- `IntelItem` (`intel_item`): `id` str(16) PK, `source` str(32), `url` text unique, `title` text, `number` str(64),
  `kind` str(32), `category` str(64), `listed_date` date null, `first_seen` timestamptz default now,
  `labor_hint` bool, `in_corpus` bool (number matches `legal_document.number`), `status` str(16)
  (`new` | `analysed` | `skipped` | `approved` | `ignored` | `blocked`), `analysis` text (JSON) null, `error` text
  null, `reviewed_by` str(32) null, `reviewed_at` timestamptz null.
- `IntelRun` (`intel_run`): `id` PK autoincrement, `started_at`, `finished_at`, `trigger` (`schedule`|`manual`),
  `per_source` text (JSON `{source: {status, found, new}}`), `error` text null.
- Incremental: an item already stored (same URL) is never re-fetched or re-analysed.

## Analysis with Dahl (`intel/analyze.py`)
Public data = class C. Run inside `data_class_scope("C")` + `cloud_first_scope(True)` (from `app.llm.context`) so
the cloud route (Dahl) is tried first. Only items with `labor_hint` true and not `in_corpus` are analysed (others
→ `skipped`). Max 10 analyses per run (log the rest as `new` for the next run).
- Context sent to the model (all public): the item's title/number/kind/category/URL/listed date; the corpus list
  (`legal_document`: doc_id, number, title, effective/expired dates); the top 5 `search_nodes(title)` hits
  (node_id, display, first 200 chars).
- Output schema (pydantic, `extra="forbid"`), Vietnamese text fields:
  `relevant_labor: bool`, `topic: str`, `summary: str` (≤ 3 sentences, only from the title/metadata — say so when
  the full text is unknown), `what_changes: str`, `amends: list[str]` (document numbers), `replaces: list[str]`,
  `affected_nodes: list[str]` (node_ids from the provided hits only — drop anything else in code),
  `effective_date: str | null` (ISO; null unless stated in the metadata), `impact: "cao"|"trung bình"|"thấp"`,
  `impact_reason: str`, `routing: {queue: str, action: "nạp ngay"|"theo dõi"|"bỏ qua", kg_updates: list[str]}`,
  `needs_full_text: bool`, `confidence: float 0–1`.
- Prompt: explicit, numbered rules; "chỉ dựa trên dữ liệu được cung cấp; không biết thì để null và hạ
  confidence"; JSON only. Validate; on failure retry once with the validation error appended; then store
  `error` and status `new`.

## Scheduler + API
- `scheduler.py`: daemon thread; every 15 min checks whether a `schedule` run already happened today after
  `intel_daily_hour` (local time Asia/Ho_Chi_Minh); if not, runs `run_scan(trigger="schedule")`. Never two runs at
  once (a lock); `run_scan` never raises.
- Endpoints (permission `review` — admin/dev): `POST /api/intel/scan` (starts a background manual run, 409 if one
  is running) · `GET /api/intel/runs?limit=10` · `GET /api/intel/items?status=&labor=` (newest first) ·
  `POST /api/intel/items/{id}/approve` · `POST /api/intel/items/{id}/ignore` · `POST /api/intel/items/{id}/
  analyse` (re-run analysis for one item).
- Approve = status `approved` + `reviewed_by/at`; the UI then tells the user to download the full text and upload it
  in `/upload` (no automatic download of document pages — they may be blocked or copyrighted).

## Frontend `/tin-moi`
- Header: "Tin pháp luật mới", last run time + per-source status chips (OK n mới · Bị chặn · Cần trình duyệt), a
  "Quét ngay" button (disabled while running, polls `/runs` every 5 s).
- Tabs: Cần xem (analysed, labor) · Tất cả · Đã duyệt · Bỏ qua.
- Card per item: title (link), number, source, listed date, impact badge (cao đỏ / trung bình cam / thấp xám),
  summary, "Thay đổi gì", amends/replaces chips, affected articles as links `/api/law/{node_id}`, effective date or
  "chưa rõ", routing (queue + action + kg updates), confidence %, a warning "Tóm tắt chỉ từ tiêu đề — cần toàn văn"
  when `needs_full_text`, and buttons Duyệt / Bỏ qua / Phân tích lại.

## Tests (`tests/test_intel.py` — no network; httpx mocked with `httpx.MockTransport`)
1. Parsers on the committed fixtures: thuvienphapluat finds ≥ 20 items incl. number `399/2026/NĐ-CP` with category
   `Lao-dong-Tien-luong`; luatvietnam finds ≥ 15 items with absolute URLs; AnLe returns [] and `needs_browser`.
2. Fetcher: robots disallow → URL not fetched; two requests to one host wait ≥ `delay_s` (monkeypatch `time`);
   403 → item/run marked `blocked`.
3. Incremental: running the scan twice on the same fixture adds items only once; `in_corpus` true for a number
   present in `legal_document`.
4. Analysis: fake router returning valid JSON → stored, `affected_nodes` outside the hits removed; invalid JSON then
   valid → one retry; invalid twice → `error` set, status `new`; the router was called with data class C and
   cloud_first true; non-labor items → `skipped`, no router call; at most 10 analyses per run.
5. API: scan as admin → 202/200 and a run row; as user1 → 403; approve/ignore change status.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_intel.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/intel app/api/routes.py app/main.py app/config.py app/db/models.py tests/test_intel.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
