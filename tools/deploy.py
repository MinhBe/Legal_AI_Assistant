"""Triển khai demo công khai: kho luật -> Neon, backend -> Hugging Face Space (Minh 20/11/2026).

    python -X utf8 tools/deploy.py bundle     # dựng data/deploy/hf-space (không cần key)
    python -X utf8 tools/deploy.py neon       # chép kho luật lên Neon  (cần keys/neon_url.txt)
    python -X utf8 tools/deploy.py space      # đẩy backend lên Space    (cần keys/hf_token.txt)
    python -X utf8 tools/deploy.py check      # gọi /health, /docs của Space
    python -X utf8 tools/deploy.py all        # có đủ hai tệp key thì chạy cả chuỗi

Key chỉ đọc từ tệp, truyền qua biến môi trường của tiến trình con, không in ra, không ghi log.
Chỉ dữ liệu luật công khai lên Neon (không tài khoản, không hội thoại, không hồ sơ khách).
Demo chỉ dùng Dahl: key Dahl Minh tự dán vào Secrets của Space (DAHL_TOKEN_1..N).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "deploy"
BUNDLE = OUT / "hf-space"
DUMP = OUT / "lawvn_corpus.sql.gz"
NEON_FILE = ROOT / "keys" / "neon_url.txt"
HF_FILE = ROOT / "keys" / "hf_token.txt"
SPACE = os.environ.get("LAWVN_SPACE", "MinhBe/lawvn")
SPACE_URL = "https://" + SPACE.lower().replace("/", "-") + ".hf.space"

# bảng luật công khai; KHÔNG có app_user, thread, message, answer_record, intake_record, review_case,
# usage_count, case_problem (rút từ ghi âm), template, pv_chunk
TABLES = ["legal_document", "legal_node", "doc_meta", "node_reference", "node_supersession",
          "document_relation", "provision_version", "legal_link", "transition_rule", "precedent",
          "precedent_catalog", "intel_item", "intel_impact", "intel_run", "intel_doc",
          "autonomy_level", "uploaded_file", "upload_option"]

DOCKERFILE = """# Hugging Face Space (Docker, CPU miễn phí): giao diện Next.js + API FastAPI trong MỘT container.
# Dựng bởi tools/deploy.py. Trình duyệt chỉ thấy cổng 7860 (Next); /api/* được Next chuyển tới uvicorn.
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
ENV NEXT_PUBLIC_API_BASE_URL="" API_INTERNAL_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app \
    EMBEDDER=vie-v2 EMBED_DIM=1024 \
    NO_LOCAL_FOR_C=true CLOUD_FIRST_FOR_C=true CLOUD_SPREAD_MODELS=true \
    CLOUD_LLM_KEYS_DIR=/nonexistent DEMO_MODE=true HF_HOME=/tmp/hf \
    API_INTERNAL_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev curl ffmpeg \
        nodejs \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt backend/requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ml.txt "faster-whisper==1.1.1"
COPY backend/ /app/
COPY --from=web /web /web
COPY start.sh /start.sh
RUN useradd -m -u 1000 user && chown -R user /app /web && chmod +x /start.sh
USER user
EXPOSE 7860
CMD ["/start.sh"]
"""

START = """#!/bin/sh
# API trong container (chỉ 127.0.0.1), giao diện ra ngoài ở cổng 7860
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
cd /web && exec node_modules/.bin/next start -p 7860 -H 0.0.0.0
"""

README = """---
title: LawVN
emoji: ⚖️
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

LawVN: trợ lý pháp luật lao động có trích dẫn đúng phiên bản theo thời gian. Bản demo:
/demo (3 tình huống mẫu), /hieu-he-thong (bài học tương tác), /docs (API).
Secrets: DATABASE_URL (đặt tự động bởi tools/deploy.py), DAHL_TOKENS (Minh dán, tuỳ chọn).
"""

SKIP = {"tests", "data", "__pycache__", ".pytest_cache", ".ruff_cache", ".env", ".dahl.env",
        "Dockerfile", "Dockerfile.demo", "Dockerfile.space"}


def bundle() -> Path:
    shutil.rmtree(BUNDLE, ignore_errors=True)
    BUNDLE.mkdir(parents=True)
    ign = shutil.ignore_patterns("__pycache__", "*.pyc", ".env*", "node_modules", ".next", "tests",
                                 "tsconfig.tsbuildinfo", "Dockerfile*", "data", ".dahl.env")
    shutil.copytree(ROOT / "backend", BUNDLE / "backend", ignore=ign)
    shutil.copytree(ROOT / "frontend", BUNDLE / "frontend", ignore=ign)
    (BUNDLE / "backend" / "data" / "demo").mkdir(parents=True)
    shutil.copy2(ROOT / "frontend" / "lib" / "demo" / "cases.json", BUNDLE / "backend" / "data" / "demo" / "cases.json")
    # vercel.json chỉ dùng cho bản tách giao diện; bản gộp không cần
    (BUNDLE / "frontend" / "vercel.json").unlink(missing_ok=True)
    (BUNDLE / "Dockerfile").write_text(DOCKERFILE, encoding="utf-8")
    (BUNDLE / "start.sh").write_text(START, encoding="utf-8", newline="\n")
    (BUNDLE / "README.md").write_text(README, encoding="utf-8")
    leaks = [p for p in BUNDLE.rglob("*") if p.is_file() and (p.name.startswith(".env") or "keys" in p.parts
             or p.suffix in (".keys",) or p.name in ("kaggle.json", "auth.json"))]
    if leaks:
        raise SystemExit(f"gói có tệp nhạy cảm, dừng: {leaks[:3]}")
    n = sum(1 for p in BUNDLE.rglob("*") if p.is_file())
    print("gói Space:", BUNDLE, n, "tệp")
    return BUNDLE


def dump() -> None:
    """Bản sao bảng luật công khai (schema + dữ liệu, gồm vector) từ DB máy nhà."""
    OUT.mkdir(parents=True, exist_ok=True)
    args = " ".join(f"-t {t}" for t in TABLES)
    cmd = f"pg_dump -U lawvn -d lawvn --no-owner --no-privileges {args} | gzip -6"
    with DUMP.open("wb") as f:
        subprocess.run(["docker", "compose", "exec", "-T", "postgres", "sh", "-c", cmd], cwd=ROOT,
                       stdout=f, check=True)
    print("bản sao kho luật:", DUMP, round(DUMP.stat().st_size / 2**20, 1), "MB")


def _read(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"thiếu {path.name}: Minh tạo tài khoản rồi lưu vào {path}")
    return path.read_text(encoding="utf-8").strip()


def neon() -> None:
    url = _read(NEON_FILE)
    if not DUMP.exists():
        dump()
    env = {**os.environ, "NEON_URL": url}
    # chạy lại được: bỏ các bảng luật (chỉ các bảng trong TABLES) rồi nạp lại từ bản sao
    drops = " ".join(f"DROP TABLE IF EXISTS public.{t} CASCADE;" for t in TABLES)
    # Neon để search_path rỗng ở mức role: đặt public cho role này trong DB này (mức role+DB thắng mức
    # role) để app dùng tên bảng không kèm schema. \$ vì lệnh đi qua sh -c "…"
    sql = ("CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; "
           "DO \\$x\\$ BEGIN EXECUTE format('ALTER ROLE %I IN DATABASE %I SET search_path TO public', "
           "current_user, current_database()); END \\$x\\$; " + drops)
    # chạy psql trong container postgres (có sẵn psql), URL đi qua biến môi trường, không vào dòng lệnh
    base = ["docker", "compose", "exec", "-T", "-e", "NEON_URL", "postgres", "sh", "-c"]
    subprocess.run(base + [f'psql "$NEON_URL" -v ON_ERROR_STOP=1 -q -c "{sql}"'], cwd=ROOT, env=env,
                   check=True)
    with DUMP.open("rb") as f:
        r = subprocess.run(base + ['gunzip | psql "$NEON_URL" -v ON_ERROR_STOP=1 -q'], cwd=ROOT,
                           env=env, stdin=f, capture_output=True)
    if r.returncode != 0:
        msg = r.stderr.decode("utf-8", "replace").replace(url, "<neon>")[-600:]
        raise SystemExit(f"nạp Neon lỗi: {msg}")
    out = subprocess.run(base + ['psql "$NEON_URL" -At -c "select count(*) from public.legal_node"'], cwd=ROOT,
                         env=env, capture_output=True, text=True)
    print("Neon: legal_node =", out.stdout.strip())


def space() -> None:
    token = _read(HF_FILE)
    from huggingface_hub import HfApi

    api = HfApi(token=token)
    if not BUNDLE.exists():
        bundle()
    api.create_repo(SPACE, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    if NEON_FILE.exists():  # Space đọc DB từ secret, không ghi chuỗi vào mã
        # kết nối trực tiếp: pooler của Neon bỏ qua search_path đặt cho role (bảng không kèm schema lỗi)
        api.add_space_secret(SPACE, "DATABASE_URL", _read(NEON_FILE).replace("-pooler.", "."))
    api.upload_folder(folder_path=str(BUNDLE), repo_id=SPACE, repo_type="space",
                      commit_message="LawVN (tools/deploy.py)")
    print("đã đẩy lên Space:", f"https://huggingface.co/spaces/{SPACE}")


def check(wait_s: int = 1800) -> bool:
    t0 = time.time()
    while time.time() - t0 < wait_s:
        try:
            with urllib.request.urlopen(SPACE_URL + "/demo", timeout=30) as r:
                if r.status == 200:
                    print("Space chạy:", SPACE_URL + "/demo", "| bài học:", SPACE_URL + "/hieu-he-thong")
                    return True
        except Exception:  # noqa: BLE001 — đang build
            pass
        time.sleep(30)
    print("Space chưa lên sau", wait_s, "s:", SPACE_URL)
    return False


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bundle"
    if cmd == "bundle":
        bundle()
    elif cmd == "dump":
        dump()
    elif cmd == "neon":
        neon()
    elif cmd == "space":
        space()
    elif cmd == "check":
        check()
    elif cmd == "all":
        if not (NEON_FILE.exists() and HF_FILE.exists()):
            raise SystemExit("chưa đủ keys/neon_url.txt và keys/hf_token.txt")
        bundle()
        neon()
        space()
        check()


if __name__ == "__main__":
    main()
