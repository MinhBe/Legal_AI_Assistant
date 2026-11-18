"""Chạy Kaggle CLI bằng một tệp khoá trong keys/ mà KHÔNG lộ khoá.

  python tools/kaggle_run.py --key "kaggle.json" -- kernels list --mine
  python tools/kaggle_run.py --test-all          # thử mọi tệp keys/kaggle*.json, chỉ đọc

- Khoá được đọc trong tiến trình này và chỉ truyền cho đúng MỘT tiến trình con qua biến môi
  trường (KAGGLE_USERNAME/KAGGLE_KEY, hoặc KAGGLE_API_TOKEN cho token kiểu mới).
- KAGGLE_CONFIG_DIR trỏ vào thư mục tạm rỗng, để CLI không đọc/ghi ~/.kaggle.
- Mọi đầu ra đi qua bộ lọc: chuỗi khoá xuất hiện ở đâu cũng bị thay bằng [ĐÃ ẨN].
- Không bao giờ in, ghi log, băm hay chép giá trị khoá. Tên tài khoản thì được in.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEYS = ROOT / "keys"
REDACTED = "[ĐÃ ẨN]"


def _cli() -> list[str]:
    exe = shutil.which("kaggle")
    if exe:
        return [exe]
    user_scripts = Path(os.environ.get("APPDATA", "")) / "Python" / "Python312" / "Scripts" / "kaggle.exe"
    if user_scripts.exists():
        return [str(user_scripts)]
    return [sys.executable, "-m", "kaggle"]


def load_credentials(path: Path) -> tuple[dict[str, str], str, list[str]]:
    """(biến môi trường, tên tài khoản hoặc "", các chuỗi bí mật cần ẩn khỏi đầu ra)."""
    raw = path.read_text(encoding="utf-8").strip()
    try:
        data = json.loads(raw)
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("key"):
        user = str(data.get("username") or "")
        return {"KAGGLE_USERNAME": user, "KAGGLE_KEY": str(data["key"])}, user, [str(data["key"])]
    token = (data.get("token") if isinstance(data, dict) else None) or raw
    return {"KAGGLE_API_TOKEN": str(token)}, "", [str(token)]


PLACEHOLDER = "__KAGGLE_USER__"


def _stage(src: Path, dst: Path, user: str) -> None:
    """Chép thư mục dataset/kernel sang thư mục tạm, điền tên tài khoản vào *metadata.json."""
    shutil.copytree(src, dst)
    for meta in dst.glob("*metadata.json"):
        meta.write_text(meta.read_text(encoding="utf-8").replace(PLACEHOLDER, user),
                        encoding="utf-8")


def run(key_file: str, args: list[str], timeout: int = 600,
        stage: Path | None = None) -> tuple[int, str, str]:
    """Chạy `kaggle <args>`; trả (mã thoát, đầu ra đã ẩn khoá, tên tài khoản).

    `stage`: thư mục có *metadata.json chứa __KAGGLE_USER__; được chép sang thư mục tạm và
    `{STAGE}` trong args trỏ tới bản chép. __KAGGLE_USER__ trong args cũng được điền."""
    env_extra, user, secrets = load_credentials(KEYS / key_file)
    args = [a.replace(PLACEHOLDER, user) for a in args]
    if stage is not None:
        tmp = Path(tempfile.mkdtemp(prefix="kaggle-stage-")) / stage.name
        _stage(stage, tmp, user)
        args = [a.replace("{STAGE}", str(tmp)) for a in args]
    env = {k: v for k, v in os.environ.items() if not k.startswith("KAGGLE_")}
    with tempfile.TemporaryDirectory() as cfg:
        env.update(env_extra)
        env["KAGGLE_CONFIG_DIR"] = cfg
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            proc = subprocess.run(_cli() + args, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=timeout)
            out, code = (proc.stdout or "") + (proc.stderr or ""), proc.returncode
        except subprocess.TimeoutExpired:
            out, code = "hết thời gian chờ", 124
    for s in secrets:
        if s:
            out = out.replace(s, REDACTED)
    return code, out, user


def test_all() -> None:
    files = sorted(p.name for p in KEYS.iterdir() if p.name.lower().startswith("kaggle"))
    for name in files:
        code, out, user = run(name, ["kernels", "list", "--mine", "--page-size", "5"], timeout=120)
        first = " ".join(out.strip().splitlines()[:3])[:300]
        print(json.dumps({"key_file": name, "username": user or "(token kiểu mới)",
                          "exit": code, "output": first}, ensure_ascii=False))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--key", help="tên tệp trong keys/")
    p.add_argument("--test-all", action="store_true")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--stage", help="thư mục dataset/kernel có __KAGGLE_USER__ trong metadata")
    p.add_argument("rest", nargs=argparse.REMAINDER)
    a = p.parse_args()
    if a.test_all:
        test_all()
        return
    rest = a.rest[1:] if a.rest[:1] == ["--"] else a.rest
    code, out, _user = run(a.key, rest, timeout=a.timeout,
                           stage=Path(a.stage).resolve() if a.stage else None)
    sys.stdout.write(out)
    sys.exit(code)


if __name__ == "__main__":
    main()
