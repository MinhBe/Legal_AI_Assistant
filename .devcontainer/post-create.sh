#!/usr/bin/env bash
# Chạy một lần khi tạo Codespace: cài thư viện backend + frontend, cài Pi, ghi key từ secrets.
# Giữ nhẹ: torch bản CPU (không kéo CUDA vài GB), không Ollama, không faster-whisper/GPU, không Docker.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "== backend (Python) =="
python -m pip install --upgrade --quiet pip
# sentence-transformers trong requirements.txt kéo torch; cài bản CPU trước để pip không lấy bản CUDA
python -m pip install --quiet torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install --quiet -r backend/requirements.txt -r backend/requirements-dev.txt

echo "== frontend (Next.js) =="
(cd frontend && npm install --no-fund --no-audit)

echo "== git hooks (kiểm commit theo .gitmessage) =="
git config core.hooksPath .githooks
git config commit.template .gitmessage

echo "== Pi =="
bash .devcontainer/pi/setup-pi.sh
bash .devcontainer/pi/write-keys.sh || true

echo "Xong. Chạy app: bash .devcontainer/dev.sh   |   Chạy Pi: pi-role lead"
