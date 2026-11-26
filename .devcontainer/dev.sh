#!/usr/bin/env bash
# Chạy API (cổng 8000) và web (cổng 3000) cùng lúc trong Codespace. Ctrl+C để dừng cả hai.
# Web gọi API qua /api/* cùng địa chỉ (API_INTERNAL_URL trong devcontainer.json), nên chỉ cần mở cổng 3000.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -n "${DATABASE_URL:-}" ] || echo "Cảnh báo: chưa có secret DATABASE_URL, API sẽ thử Postgres localhost (không có)."
trap 'kill 0' EXIT
(cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload) &
(cd frontend && npm run dev -- -p 3000) &
wait
