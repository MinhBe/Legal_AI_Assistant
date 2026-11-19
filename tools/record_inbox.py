"""Thư mục nhận ghi âm: RAG\\RAG\\record\\inbox\\ -> Kaggle ASR -> Kaggle che PII -> bản đã che về máy.

Minh 19/11/2026: nguồn nào cũng được (Minh tự thu thập, có quyền dùng). Máy nhà KHÔNG chạy việc nặng:
chép lời và che PII đều chạy trên Kaggle (tài khoản minhart, private); máy chỉ tải bản ĐÃ CHE.
Không có phần cào mạng xã hội hay vượt đăng nhập: chỉ xử lý tệp Minh tự đặt vào thư mục.

    python -X utf8 tools/record_inbox.py            # một lượt: có tệp mới thì đẩy lên và chạy
    python -X utf8 tools/record_inbox.py --collect  # sau khi kernel xong: tải bản đã che về

Trạng thái lưu ở record/inbox/.state.json (tên tệp đã xử lý). Bản gốc trong inbox không bị xoá.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INBOX = ROOT / "record" / "inbox"
STAGE = ROOT / "data" / "finetune" / "kaggle_stage" / "minhart"
DS_REC = STAGE / "ds_recordings"
OUT = ROOT / "data" / "raw" / "record" / "out"
EXTS = {".mp4", ".m4a", ".mp3", ".wav", ".aac", ".ogg", ".webm", ".mkv", ".mov"}
STATE = INBOX / ".state.json"


def kaggle(*args: str, timeout: int = 1800) -> str:
    exe = Path.home() / "AppData/Roaming/Python/Python312/Scripts/kaggle.exe"
    cmd = [str(exe)] if exe.exists() else [sys.executable, "-m", "kaggle"]
    proc = subprocess.run(cmd + list(args), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, env={**__import__("os").environ,
                                                                   "PYTHONUTF8": "1"})
    return (proc.stdout or "") + (proc.stderr or "")


def stem_of(p: Path) -> str:
    return p.stem.replace(" ", "_")


def wait(kernel: str, every: int = 120, limit_s: int = 6 * 3600) -> str:
    t0 = time.time()
    while time.time() - t0 < limit_s:
        s = kaggle("kernels", "status", kernel, timeout=120)
        if any(x in s for x in ("COMPLETE", "ERROR", "CANCEL")):
            return s.strip()
        time.sleep(every)
    return "timeout"


def push_new() -> list[str]:
    INBOX.mkdir(parents=True, exist_ok=True)
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"done": []}
    done = set(state["done"]) | {stem_of(p) for p in DS_REC.glob("*") if p.suffix.lower() in EXTS}
    new = [p for p in sorted(INBOX.iterdir()) if p.suffix.lower() in EXTS and stem_of(p) not in done]
    if not new:
        print("không có tệp mới trong", INBOX)
        return []
    for p in new:  # bản sao vào thư mục dataset; bản gốc giữ nguyên
        shutil.copy2(p, DS_REC / f"{stem_of(p)}{p.suffix.lower()}")
    # tệp đã chép ở lượt trước: notebook ASR bỏ qua
    (DS_REC / "skip.json").write_text(json.dumps(sorted(done)), encoding="utf-8")
    print(kaggle("datasets", "version", "-p", str(DS_REC), "-m",
                 f"inbox: +{len(new)} tệp").strip()[-200:])
    time.sleep(90)  # đợi phiên bản dataset sẵn sàng
    print(kaggle("kernels", "push", "-p", str(STAGE / "kernel_asr")).strip()[-200:])
    print("ASR:", wait("minhart/lawvn-asr"))
    print(kaggle("kernels", "push", "-p", str(STAGE / "kernel_mask")).strip()[-200:])
    print("che PII:", wait("minhart/lawvn-pii-mask"))
    state["done"] = sorted(done | {stem_of(p) for p in new})
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return [stem_of(p) for p in new]


def collect() -> None:
    """Chỉ tải bản ĐÃ CHE (*.masked.json) từ kernel che PII về data/raw/record/out/."""
    OUT.mkdir(parents=True, exist_ok=True)
    print(kaggle("kernels", "output", "minhart/lawvn-pii-mask", "-p", str(OUT),
                 "--file-pattern", r".*\.masked\.json$", "-o", "-q").strip()[-300:])
    for f in sorted((OUT / "masked").glob("*.masked.json")) if (OUT / "masked").exists() else []:
        shutil.move(str(f), OUT / f.name)
    print("bản đã che:", sorted(p.name for p in OUT.glob("*.masked.json")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", action="store_true")
    a = ap.parse_args()
    if a.collect:
        collect()
        return
    if push_new():
        collect()


if __name__ == "__main__":
    main()
