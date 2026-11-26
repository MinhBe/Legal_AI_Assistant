#!/usr/bin/env bash
# Ghi key từ Codespaces secrets ra $PI_HOME/keys/<provider>.keys (Pi) và $CLOUD_LLM_KEYS_DIR (app).
# Chạy mỗi lần Codespace khởi động, nên đổi secret rồi Restart là có key mới.
# Không in giá trị key, chỉ in số lượng.
set -euo pipefail
PI_HOME="${PI_HOME:-/workspaces/.pi-dev}"
mkdir -p "$PI_HOME/keys"; chmod 700 "$PI_HOME/keys"
umask 077

write() {  # write <provider> <nội dung secret: nhiều dòng hoặc cách nhau bằng dấu phẩy>
  local p="$1" v="$2"
  [ -n "$v" ] || return 0
  printf '%s\n' "$v" | tr ',' '\n' | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//' | grep -v '^$' \
    > "$PI_HOME/keys/$p.keys"
  echo "pi keys: $p = $(wc -l < "$PI_HOME/keys/$p.keys") key"
}

# Dahl: dùng chung secret với app (DAHL_TOKENS, hoặc DAHL_TOKEN_1..30)
dahl="${DAHL_TOKENS:-}"
for i in $(seq 1 30); do v="$(printenv "DAHL_TOKEN_$i" || true)"; [ -n "$v" ] && dahl+=$'\n'"$v"; done
write dahl "$dahl"
# app đọc key Dahl từ CLOUD_LLM_KEYS_DIR (thư mục riêng, để app không đọc nhầm key OpenRouter/ScaleRouter)
APP_KEYS="${CLOUD_LLM_KEYS_DIR:-/workspaces/.app-keys}"
mkdir -p "$APP_KEYS"; chmod 700 "$APP_KEYS"
if [ -s "$PI_HOME/keys/dahl.keys" ]; then cp "$PI_HOME/keys/dahl.keys" "$APP_KEYS/dahl.keys"; fi
write openrouter "${OPENROUTER_KEYS:-}"
write scalerouter "${SCALEROUTER_KEYS:-}"
