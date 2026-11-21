"""LawVN trên Modal (Minh 21/11/2026: chọn Modal vì Space Docker của Hugging Face cần gói PRO).

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
secrets = [modal.Secret.from_name("lawvn-db")]
if os.environ.get("LAWVN_DAHL") == "1":
    secrets.append(modal.Secret.from_name("lawvn-dahl"))


@app.function(image=image, secrets=secrets, cpu=2.0, memory=6144, timeout=900,
              scaledown_window=900, max_containers=1)
@modal.concurrent(max_inputs=50)
@modal.web_server(port=7860, startup_timeout=600)
def web() -> None:
    import subprocess

    subprocess.Popen(["/start.sh"])


# Giữ máy chủ luôn thức (Minh 21/11/2026): cứ 10 phút gọi GET một lần, ngắn hơn scaledown_window
# (15 phút) nên container không bao giờ tắt. Chạy ngay trên Modal, không cần máy Minh bật.
# Tắt: đặt LAWVN_KEEP_WARM=0 khi deploy. Chi phí: container chạy liên tục (2 CPU, 6 GiB).
PUBLIC_URL = "https://minhbe--lawvn-web.us-east.modal.run"

if os.environ.get("LAWVN_KEEP_WARM", "1") != "0":
    @app.function(image=modal.Image.debian_slim(), schedule=modal.Period(minutes=10), timeout=660)
    def keep_warm() -> None:
        import time
        import urllib.request

        for path in ("/api/docgen/templates", "/demo"):  # API + Neon cũng thức
            t = time.time()
            try:
                with urllib.request.urlopen(PUBLIC_URL + path, timeout=600) as r:
                    print(f"GET {path} -> {r.status} ({time.time() - t:.1f}s)")
            except Exception as e:  # cold start lần đầu có thể chậm; lần sau thử lại
                print(f"GET {path} lỗi: {e!r} ({time.time() - t:.1f}s)")
