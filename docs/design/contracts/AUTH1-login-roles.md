# Contract AUTH1 — demo login, roles enforced on the API, daily quotas

Spec: gap item AUTH1 (`docs/design/v1.1-gap.md`). Read `AGENTS.md` first. Do not commit. Never read `.env`.
**No new packages**: hashing with `hashlib.pbkdf2_hmac` (stdlib), tokens signed with `hmac` (stdlib).
These are DEMO accounts for a local machine; the README must say so loudly.

## Files you may create or edit (nothing else)
- `backend/app/auth/__init__.py`, `roles.py`, `accounts.py`, `tokens.py`, `deps.py`, `quota.py` (new)
- `backend/app/db/models.py` (add `AppUser`, `UsageCount` at the end)
- `backend/app/config.py` (`auth_required: bool = True`, `auth_secret: str | None = None`)
- `backend/app/main.py` (seed accounts at startup; CORS `allow_headers` must include `Authorization` and
  `X-Client-Id`)
- `backend/app/api/routes.py` (add dependencies to routes; new `/api/auth/*`, `/api/dev/*`)
- `backend/app/llm/context.py` + `backend/app/llm/router.py` (only a `cloud_first` ContextVar, OR-ed with
  `settings.cloud_first_for_c` in `_tiered_plan`; A/B stay local-only)
- `backend/app/agent/pipeline.py` (set `cloud_first` per step like the other scopes, from a `run_chat` argument)
- `backend/tests/conftest.py` (autouse fixture: `auth_required=False` for all existing tests),
  `backend/tests/test_auth.py` (new; turns enforcement on)
- Frontend: `frontend/lib/api.ts` (new `apiFetch`), `frontend/lib/auth.tsx` (new context/provider),
  `frontend/app/login/page.tsx` (new), `frontend/app/layout.tsx`, `frontend/components/chat/Sidebar.tsx`,
  `frontend/lib/chat/useChat.ts`, `frontend/lib/chat/storage.ts`, `frontend/components/chat/MessageList.tsx`
  (hide "gửi luật sư" when not allowed), every file under `frontend/app` and `frontend/components` that calls
  `fetch(` (replace with `apiFetch`), `frontend/app/globals.css` (only new `.auth-*` rules)
- `README.md` (one warning section)

## Roles — ONE config file `backend/app/auth/roles.py` (Minh edits only this file later)
```
ROLES = {
  "anonymous": {"perms": {"chat", "calc"}, "daily": 10, "history": False, "cloud_first": False},
  "guest":     {"perms": {"chat", "calc"}, "daily": 20, "history": True,  "cloud_first": False},
  "guest_vip": {"perms": {"chat", "calc", "escalate"}, "daily": None, "history": True, "cloud_first": True},
  "user":      {"perms": {"chat", "calc", "escalate"}, "daily": 50, "history": True, "cloud_first": False},
  "admin":     {"perms": {"chat", "calc", "escalate", "upload", "graph", "review"}, "daily": None,
                "history": True, "cloud_first": False},
  "dev":       {"perms": {"chat", "calc", "escalate", "upload", "graph", "review", "dev"}, "daily": None,
                "history": True, "cloud_first": False},
}
ACCOUNTS = {"admin": "admin", "dev": "dev", "user1": "user", "user2": "user", "user3": "user",
            "guest1": "guest_vip", "guest2": "guest", "guest3": "guest"}   # password = username (demo)
```
`daily: None` = unlimited.

## Backend
- `AppUser` (`app_user`): `username` str(32) PK, `role` str(16), `salt` str(32), `pw_hash` str(64),
  `created_at`. `accounts.seed(db)` inserts missing ACCOUNTS (pbkdf2_hmac sha256, 200k iterations, random salt)
  and updates the role if it changed in `roles.py`; never stores plaintext. `verify(db, username, password)`.
- `tokens.py`: token = base64url(`username|role|expires_ts`) + "." + hmac-sha256 signature; 12 h lifetime.
  Secret = `settings.auth_secret` or, if empty, a random secret created once in `/app/data/.auth_secret`
  (file mode 600; `data/.auth_secret` must be added to `.gitignore` — you may edit `.gitignore` for that one line).
  Tampered/expired → anonymous.
- `deps.py`: `current_user(request)` → `{"username" | None, "role", "client_id"}` from `Authorization: Bearer`;
  no/invalid token → role `anonymous`, `client_id` from header `X-Client-Id` (fallback client IP).
  `require(perm)` dependency → 401 for anonymous lacking perm ("Cần đăng nhập"), 403 for a logged-in role lacking
  it ("Tài khoản {role} không có quyền này"). When `settings.auth_required` is False everything is allowed
  (tests/dev switch), but `current_user` still works.
- `quota.py`: `UsageCount` (`usage_count`): `key` str(80), `day` date, `n` int, PK (key, day).
  `check_and_count(db, user)` before each chat: key = `user:{username}` or `anon:{client_id}`; over the role's
  `daily` → HTTP 429 "Đã hết {daily} câu hỏi hôm nay cho tài khoản {role}"; returns remaining.
- Routes (enforce on the server):
  - public: `/health`, `/api/law/*`, `/api/law_as_of`, `/api/node/*`, `/api/documents`, `/api/search`,
    `/api/pv*`, `/api/gateway/preview`.
  - `chat`: `POST /api/chat` (+ quota; pass `cloud_first=ROLES[role]["cloud_first"]` to `run_chat`;
    add `"remaining"` to the SSE `start` event).
  - `calc`: `/api/calc/*`. `history`-roles only: `GET /api/threads` (403 otherwise).
  - `escalate`: `POST /api/escalate`; `GET /api/escalations/{id}` stays open (the chat card polls it).
  - `upload`: all `/api/uploads*`, `/api/admin/*`. `graph`: `GET /api/graph`.
  - `review`: `/api/review/*`, `GET /api/escalations`, `PATCH /api/escalations/*`, `/api/answers*`,
    `/api/report*`, `/api/draft/*`, `/api/precedent`.
  - `dev`: new `GET /api/dev/config` (setting NAMES and non-secret values only — never any `*key*`, `*token*`,
    `*secret*`, `*password*`, `database_url` value; show those as "đã đặt"/"trống") and `GET /api/dev/logs?n=100`
    (last n rows of `data/metrics/llm_calls.jsonl`, already free of question text).
  - `POST /api/auth/login` `{username, password}` → `{token, username, role, perms, daily}` or 401;
    `GET /api/auth/me` → current user + perms + remaining today; logout is client-side (drop the token).
- `pipeline.run_chat(..., cloud_first=False)` wraps steps in a `cloud_first_scope`; router `_tiered_plan` uses
  cloud first for level C when the context flag or the setting is true. Level A/B are unchanged (local only).

## Frontend
- `lib/api.ts`: `apiFetch(path, init)` adds `Authorization` when logged in and `X-Client-Id` (random uuid stored in
  localStorage `lawvn_client_id`); all existing `fetch(` calls to the API go through it (incl. the SSE chat stream).
  On 401/403 from a protected page show a clear message with a "Đăng nhập" link.
- `lib/auth.tsx`: provider with `user`, `login`, `logout`, `can(perm)`; token in localStorage `lawvn_token`.
- `/login`: username/password form, list of demo accounts shown as a hint box (demo only).
- Sidebar: user badge (username + role, "DEV" tag for dev, "VIP" for guest1) + "Đăng xuất", or "Đăng nhập" for
  anonymous; hide links the role cannot use (Tải lên, Đồ thị, Bàn duyệt, Dashboard for non-admin/dev). Show
  "Còn {n} câu hôm nay" when the role has a quota.
- Pages `/upload`, `/graph`, `/review`, `/dashboard`: when `!can(...)` render "Trang này chỉ dành cho admin/dev"
  + login link (the API refuses anyway).
- Anonymous: conversations are NOT written to localStorage (memory only; a banner "Khách vãng lai: lịch sử
  không được lưu"); logged-in roles with `history` keep using localStorage, namespaced by username.
- Hide the "gửi luật sư" action when `!can("escalate")`.
- 429 from chat → show the quota message in the chat.

## README
A section "⚠️ Tài khoản demo" listing the accounts and saying the passwords equal the usernames, are for a local
demo only, and must be changed (and `AUTH_SECRET` set) before any public deployment.

## Tests (`tests/test_auth.py`, with `auth_required=True`)
1. Passwords stored hashed (no plaintext in `app_user`), `verify` true/false.
2. Login: good → token; wrong → 401; tampered token → treated as anonymous; expired → anonymous.
3. Access matrix (TestClient; a fake pipeline for `/api/chat`): anonymous → chat 200, calc 200, uploads 401,
   graph 401, review 401, escalate 401; guest2 → uploads 403, escalate 403; guest1 → escalate allowed;
   user1 → escalate allowed, uploads 403; admin → uploads/graph/review 200, dev/config 403; dev → dev/config 200
   and no secret value appears in it.
4. Quota: anonymous 10/day per `X-Client-Id` → 11th is 429; a different client id still works; guest1 unlimited.
5. VIP: chat as guest1 runs with the `cloud_first` context true at level C (record it in the fake pipeline) and
   false for user1; a level-B message from guest1 still plans local only (router test).

## Done when
```
docker compose exec -T api python -m pytest -q tests/test_auth.py
docker compose exec -T api python -m pytest -q -m "not llm"
docker compose exec -T api python -m scripts.eval_gate
docker compose exec -T api ruff check --select F,E9,B905,UP,SIM114,PLW2901 app/auth app/api/routes.py app/main.py app/config.py app/llm app/agent/pipeline.py tests/test_auth.py
docker compose exec -T web npx tsc --noEmit
bash scripts/e2e-upload.sh   # may need an admin token: if it fails only on 401, add a login step to the script (you may edit it)
```
Max 2 fix attempts per failure, then stop and report. Finish with a 5-line summary.
