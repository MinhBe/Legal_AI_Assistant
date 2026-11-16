# Contract LI2b — impact beyond the document: articles, calculators, golden set, past answers; alerts + digest

Spec: gap item LI2 (second half). Builds on LI1/LI2a (`app/intel/*`, analysis JSON from Dahl with `topic`,
`affected_nodes`, `impact`, `routing`), R1/R2 (`review_case`, `/review`), T7 (`answer_record`), G3 (golden set),
I2 (`app/calc/labor.py`, `/tinh`). Read `AGENTS.md` first. Do not commit. Never read `.env`. No new packages.
The impact list is computed by CODE from the stored Dahl analysis (no extra LLM call).

## Files you may create or edit (nothing else)
- `backend/app/intel/impact.py` (new), `backend/app/intel/alerts.py` (new)
- `backend/app/intel/analyze.py` (call `impact.compute` + `alerts.raise_for` after a successful analysis)
- `backend/app/intel/store.py`
- `backend/app/db/models.py` (add `IntelImpact` only)
- `backend/app/api/routes.py` (`/api/intel/*`; the calc endpoint only to attach the warning)
- `backend/app/calc/labor.py` (only: a `warnings` list in the result dict, filled by the route — or attach in the
  route without touching labor.py; pick the smaller change)
- `backend/tests/test_intel_impact.py` (new)
- `frontend/app/tin-moi/page.tsx`, `frontend/app/tinh/page.tsx`, `frontend/components/chat/Sidebar.tsx` (badge),
  `frontend/app/globals.css` (only `.intel-*` / `.calc-warn*`)

## `intel/impact.py`
`compute(db, item, analysis) -> dict` stored in `IntelImpact` (`intel_impact`: `item_id` PK, `computed_at`,
`articles` JSON, `calculators` JSON, `golden` JSON, `answers` JSON, `summary` text):
- **articles**: `analysis.affected_nodes` (already restricted to real nodes) + nodes of corpus documents whose
  number appears in `analysis.amends`/`replaces` (article-level nodes only, max 30) → `[{node_id, display}]`.
- **calculators**: map by keywords on title + topic + what_changes (diacritic-insensitive via `guard.normalize`):
  lương tối thiểu / tiền lương / mức lương → `severance`, `job-loss`, `unlawful-dismissal`; báo trước / chấm dứt hợp
  đồng → `notice`; trợ cấp thôi việc / mất việc / thời gian làm việc → `severance`, `job-loss`, `service-years`;
  thời hiệu / tranh chấp lao động → `limitation`. Output `[{kind, reason}]`.
- **golden**: rows of `backend/eval/golden_v2.jsonl` whose `expected_provisions` hit any affected article, or whose
  question matches the calculator keywords → `[{id, question}]` (max 20).
- **answers**: `answer_record` rows whose `provisions` cite an affected article (JSON contains the node id) or whose
  masked question matches the keywords, newest first, max 20 → `[{id, created_at, question (first 120 chars)}]`.
- `summary`: one Vietnamese line, e.g. "Ảnh hưởng: 3 điều luật, 3 máy tính, 4 câu golden, 7 hồ sơ tra cứu".

## Calculator warning
`active_calc_warnings(db) -> dict[kind, list[{item_id, title, url}]]`: impacts whose item status is `analysed`
(not yet approved/ignored) and impact `cao` or `trung bình`. `POST /api/calc/{kind}` adds
`"warnings": ["Có văn bản mới có thể thay đổi kết quả — chờ luật sư duyệt: {title}"]` when the kind is listed;
`/tinh` shows them as an amber banner above the result with a link to `/tin-moi`. Approving or ignoring the item
clears the warning.

## Alerts + digest (`intel/alerts.py`)
- `raise_for(db, item, analysis, impact)`: when impact is `cao` OR watchlist priority is 3 → create one
  `ReviewCase(source="intel", status="pending", question=item title, risk_score="intel", reasons=[{"code":
  "intel", "message": "<impact_reason>"}, …impact summary…], case_type="intel")` (idempotent per item: store the case
  id in the impact row; never two cases for one item). Optional webhooks: settings `intel_webhook_url: str = ""`
  (empty = off; when set, POST a short JSON; failures logged and ignored) — add the setting to `config.py`? No:
  `config.py` is not in the list; read it with `getattr(get_settings(), "intel_webhook_url", "")` so it stays off.
- `GET /api/intel/alerts` → `{unseen: n, items: [...]}` where unseen = high items created after the user's
  last visit (store `last_seen_at` per username in a tiny table? Not allowed — keep it client-side: the endpoint
  returns high items with `created_at`, the frontend compares with `localStorage["intel_seen_at"]`).
- `GET /api/intel/digest?days=7` → `[{day, items: [{id, title, impact, priority, impact_summary}]}]` grouped by
  `first_seen` date (Asia/Ho_Chi_Minh), newest day first, impact `cao` first within a day.

## Frontend
- `/tin-moi`: new tab "Bản tin theo ngày" (digest), per item an "Ảnh hưởng" panel with linked lists: articles →
  `/api/law/{node_id}`, calculators → `/tinh?tab=<kind>`, golden ids, answers → `/api/answers/{id}`; a "Đã tạo ca
  luật sư" chip linking to `/review` when a case exists.
- Sidebar: red badge with the unseen high-impact count next to "Tin pháp luật mới" (only for `can("review")`);
  visiting `/tin-moi` sets `intel_seen_at`.
- `/tinh`: amber banner from `warnings`.

## Tests (`tests/test_intel_impact.py`, fixtures + DB, clean up rows you create; no network, no LLM)
1. `compute` for a fake analysis about "mức lương tối thiểu" with one affected node `blld2019-d90`: calculators
   include severance/job-loss/unlawful-dismissal; golden rows whose provisions include that node are listed; an
   `answer_record` citing it is listed.
2. Calculator warning appears on `POST /api/calc/severance` while the item is `analysed`, disappears after approve.
3. `raise_for`: impact `cao` → exactly one `review_case` (source intel) even when called twice; impact `thấp` and
   priority < 3 → none.
4. Digest groups by day and orders `cao` first; alerts endpoint lists only high items; both require `review`.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_intel_impact.py tests/test_intel_v2.py tests/test_intel.py tests/test_calc.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/intel app/api/routes.py app/db/models.py app/calc tests/test_intel_impact.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
