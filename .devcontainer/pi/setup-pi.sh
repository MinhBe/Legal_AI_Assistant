#!/usr/bin/env bash
# Cài Pi (pi.dev) vào Codespace, giống pi-dev trên máy Minh nhưng chạy Linux.
#   PI_HOME mặc định /workspaces/.pi-dev: nằm ngoài repo nên không lọt vào git, và /workspaces
#   được giữ khi Rebuild container, nên đăng nhập Codex (agent/auth.json) không mất.
# Chạy lại an toàn: không ghi đè auth.json, codex-accounts.json hay keys/.
set -euo pipefail
KIT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI_HOME="${PI_HOME:-/workspaces/.pi-dev}"
PI_VERSION="1.6.0"
ADDY_SHA="301b02b12bff98e4688e6984af6556802322bbde"   # versions.lock: addyosmani/agent-skills

command -v jq >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq jq; }
mkdir -p "$PI_HOME"/{agent,bin,profiles,keys,vendor,runtime}
chmod 700 "$PI_HOME/keys"

# 1) cấu hình (ghi đè được: lấy từ repo); tệp của người dùng thì chỉ chép khi chưa có
cp -r "$KIT/agent/extensions" "$PI_HOME/agent/"
cp "$KIT/agent/models.json" "$KIT/agent/APPEND_SYSTEM.md" "$KIT/agent/THIRD_PARTY_NOTICES.md" "$PI_HOME/agent/"
cp "$KIT/profiles/roles.json" "$PI_HOME/profiles/"
cp "$KIT/versions.lock" "$PI_HOME/"
cp "$KIT/bin/pi-rr" "$KIT/bin/pi-role" "$PI_HOME/bin/"
chmod +x "$PI_HOME/bin/"*
[ -f "$PI_HOME/agent/settings.json" ] || cp "$KIT/agent/settings.json" "$PI_HOME/agent/"
[ -f "$PI_HOME/agent/codex-accounts.json" ] || cp "$KIT/agent/codex-accounts.json" "$PI_HOME/agent/"

# 2) Pi runtime, ghim phiên bản
if [ "$(cat "$PI_HOME/runtime/.version" 2>/dev/null)" != "$PI_VERSION" ]; then
  npm install --prefix "$PI_HOME/runtime" --no-fund --no-audit --ignore-scripts \
    "@earendil-works/pi-coding-agent@$PI_VERSION"
  echo "$PI_VERSION" > "$PI_HOME/runtime/.version"
fi

# 3) skill Addy (xương sống, đúng commit trong versions.lock)
A="$PI_HOME/vendor/agent-skills"
if [ "$(git -C "$A" rev-parse HEAD 2>/dev/null)" != "$ADDY_SHA" ]; then
  rm -rf "$A"
  git init -q "$A"
  git -C "$A" fetch -q --depth 1 https://github.com/addyosmani/agent-skills "$ADDY_SHA"
  git -C "$A" checkout -q FETCH_HEAD
fi

# 4) gói Pi (cài vào agent/npm), không chạy install script của dependency
export PI_CODING_AGENT_DIR="$PI_HOME/agent"
PI="$PI_HOME/runtime/node_modules/.bin/pi"
for pkg in $(jq -r '.packages[]' "$PI_HOME/agent/settings.json"); do
  name="${pkg#npm:}"; name="${name%@*}"
  [ -d "$PI_HOME/agent/npm/node_modules/$name" ] && continue
  npm_config_ignore_scripts=true "$PI" install "$pkg"
done

# 5) PATH cho terminal mới
line="export PI_HOME=$PI_HOME; export PATH=\"\$PI_HOME/bin:\$PATH\""
grep -qxF "$line" ~/.bashrc 2>/dev/null || echo "$line" >> ~/.bashrc
echo "Pi $("$PI" --version 2>/dev/null || echo '?') sẵn sàng ở $PI_HOME. Mở terminal mới rồi gõ: pi-role lead"
