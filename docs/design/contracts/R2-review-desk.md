# Contract R2 — lawyer review desk: case package + four actions, escalations moved to the DB

Spec: `docs/design/LawVN-v1.1.md` §9.2, §9.3; gap item R2. Depends on R1 (`review_case` table, `risk` event),
T7 (`answer_record`), T2/T5 (`TimeFrameBox`, verifier data). Read `AGENTS.md` first. Do not commit. Never read
`.env`. No new packages (use Python `difflib` for diffs).

## Files you may create or edit (nothing else)
- `backend/app/review/__init__.py`, `backend/app/review/service.py` (new)
- (no model changes: `ReviewCase` from R1 already has `reply`, `thread_id`, `case_type`; `create_all` cannot add
  columns to an existing table)
- `backend/app/api/routes.py` (escalation endpoints re-backed by the table; new review endpoints)
- `backend/tests/test_review_desk.py` (new); `backend/tests/test_escalation.py` (adapt only where the storage
  changed; the HTTP contract must stay the same)
- `frontend/app/review/page.tsx` (new), `frontend/app/dashboard/page.tsx` (one link to `/review`),
  `frontend/app/globals.css` (only new `.rv-*` rules); you may import `TimeFrameBox` from
  `components/chat/AnswerParts.tsx` (do not change that file)

## Backend
- `review/service.py`:
  - `ERROR_LABELS = {"sai_trich_dan": "Sai trích dẫn", "sai_phien_ban": "Sai phiên bản luật", "thieu_can_cu":
    "Thiếu căn cứ", "sai_tinh_toan": "Sai tính toán", "sai_su_kien": "Hiểu sai tình tiết", "van_phong": "Văn
    phong", "khac": "Khác"}`.
  - `package(db, case_id) -> dict`: the case + linked answer record (question, answer draft, timeframe,
    verifier, provisions with node text from `legal_node`, prompt_version, model, risk reasons). Cases without an
    answer record (user escalations) still return a package with question only.
  - `act(db, case_id, action, text="", labels=[], reason="") -> dict` with action in `approve` | `light_edit` |
    `heavy_edit` | `reject`:
    - `approve`: status `approved`, `reviewer_text` = the draft answer.
    - `light_edit`: `text` required; status `light_edit`; `diff` = unified diff draft → text.
    - `heavy_edit`: `text` and ≥ 1 label required; status `heavy_edit`; diff + labels + reason.
    - `reject`: `reason` required, labels optional; status `rejected`.
    - Sets `reviewed_at`; refuses (ValueError → HTTP 409) when the case is not `pending`; validates labels against
      `ERROR_LABELS` (→ 422).
  - `import_json_escalations(db, path)`: one-time import of `data/escalations.json` rows into `review_case`
    (`source="user"`, keep id, question, thread_id, status mapping pending→pending, approved→approved with
    `reply`, denied→rejected with `reason`); idempotent (skip ids already present). Called once from the
    escalation endpoints' first use or from app start — pick one and document it.
- Escalation endpoints keep their exact request/response shapes (the chat approval card depends on them):
  `POST /api/escalate` creates a `ReviewCase(source="user", status="pending")`; `GET /api/escalations` and
  `GET /api/escalations/{id}` read the table and return the old dict shape (`id, question, thread_id, status,
  created_at, reply, resolved_at`) with status `approved` for approved/light_edit/heavy_edit and `denied` for
  rejected; `PATCH /api/escalations/{id}` maps approved → `act(..., "light_edit" if reply differs from draft
  else "approve")` — for user escalations without a draft use `approve` with `reviewer_text = reply`; denied →
  `reject` with reason = reply.
- New: `GET /api/review/cases/{id}/package`, `POST /api/review/cases/{id}/act` (`{action, text, labels,
  reason}`), `GET /api/review/labels`, `GET /api/review/stats` → counts per status and per label (for §9.3
  "tỷ lệ duyệt thẳng").

## Frontend `/review`
- Left: case list (pending first; filter tabs: Chờ duyệt / Đã xử lý / Tất cả), each with risk score chip,
  source (Tự động / Người dùng gửi), time ago, first 120 chars of the question.
- Right: case package — question; "Lý do vào hàng đợi" (risk reasons); "Phương án trả lời" (draft, editable
  textarea); `TimeFrameBox`; Verifier problems; cited provisions with their text (collapsible); model + prompt
  version line.
- Actions: four buttons "Duyệt thẳng", "Sửa nhẹ", "Sửa nhiều", "Từ chối"; label checkboxes + reason field appear
  for "Sửa nhiều"/"Từ chối"; show server validation errors; after success the case moves to "Đã xử lý" and shows
  the diff (monospace, +/- coloured).
- Stats strip on top: pending count, approved-straight rate, top error labels.
- Dashboard: a "Bàn duyệt luật sư →" link to `/review`.

## Tests (`tests/test_review_desk.py`, TestClient + DB, clean up rows you create)
1. Auto case (insert an answer_record + review_case) → package has draft, timeframe, provisions with text.
2. Each action: approve / light_edit (diff contains the change) / heavy_edit (requires label: 422 without) /
   reject (requires reason); acting twice → 409.
3. Escalation compatibility: POST /api/escalate → GET /api/escalations lists it with status `pending`; PATCH
   approved with reply → GET /api/escalations/{id} returns status `approved` and the reply; PATCH denied → status
   `denied`.
4. `import_json_escalations` on a temp JSON file imports rows once (second call imports 0).
5. `/api/review/stats` counts match.

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_review_desk.py tests/test_escalation.py tests/test_risk.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/review app/api/routes.py app/db/models.py tests/test_review_desk.py
docker compose exec -T web npx tsc --noEmit
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
