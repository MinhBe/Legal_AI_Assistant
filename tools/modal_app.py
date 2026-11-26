"""Legal Agentic trên Modal (Minh 21/11/2026: chọn Modal vì Space Docker của Hugging Face cần gói PRO).

    python -X utf8 tools/deploy.py bundle          # dựng data/deploy/hf-space (giao diện + API)
    modal deploy tools/modal_app.py                # đẩy lên workspace của token trong ~/.modal.toml

Dùng lại Dockerfile của gói (Next.js ở cổng 7860, uvicorn 127.0.0.1:8000 trong cùng container).
CPU, tự tắt khi không có người dùng (trả tiền theo thời gian chạy, nằm trong tín dụng miễn phí).
DATABASE_URL nằm trong secret "lawvn-db" của Modal (kết nối trực tiếp tới Neon, không qua pooler);
không ghi vào mã. Key Dahl: Minh thêm secret "lawvn-dahl" (biến DAHL_TOKENS) trên
trang Modal nếu muốn demo gọi AI thật; chưa có thì /demo dùng câu trả lời ghi sẵn.
"""

from __future__ import annotations

import os
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "data" / "deploy" / "hf-space"


image = modal.Image.from_dockerfile(str(BUNDLE / "Dockerfile"), context_dir=str(BUNDLE))
app = modal.App("lawvn")

# Secret có tên, khai báo giống nhau ở máy deploy và trong container (khai báo có điều kiện làm
# container không khởi động được). lawvn-db: DATABASE_URL, tạo bằng `modal secret create lawvn-db
# --from-dotenv`; lawvn-dahl: DAHL_TOKENS, Minh tạo trên trang Modal (tuỳ chọn, đặt LAWVN_DAHL=1).
secrets = [modal.Secret.from_name("lawvn-db"), modal.Secret.from_name("lawvn-admin")]  # lawvn-admin: LAWVN_ADMIN_PASSWORD
if os.environ.get("LAWVN_DAHL") == "1":
    secrets.append(modal.Secret.from_name("lawvn-dahl"))


@app.function(image=image, secrets=secrets, cpu=2.0, memory=6144, timeout=900,
              scaledown_window=900, max_containers=1)
@modal.concurrent(max_inputs=50)
@modal.web_server(port=7860, startup_timeout=600, label="tuvanphapluat")
def web() -> None:
    import subprocess

    subprocess.Popen(["/start.sh"])
