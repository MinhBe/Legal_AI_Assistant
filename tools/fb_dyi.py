"""Nhập bản xuất "Tải thông tin của bạn" (DYI) của CHÍNH tài khoản Facebook của Minh.

Minh 19/11/2026: lấy video từ Facebook của mình bằng con đường hợp lệ là bản xuất DYI
(Cài đặt > Thông tin của bạn > Tải thông tin, định dạng JSON). Không cào, không đăng nhập hộ.

Thả facebook-*.zip vào RAG\\RAG\\record\\inbox\\ rồi chạy tools/record_inbox.py: mỗi video trong
zip được chép ra inbox dưới tên fb_<thời điểm>_<n>.<đuôi>, kèm một dòng trong
record/inbox/fb_dyi_manifest.jsonl (caption, thời điểm, source="facebook-dyi"), rồi đi tiếp
đường Kaggle ASR -> Kaggle che PII như mọi tệp khác.

    python -X utf8 tools/fb_dyi.py <facebook-xxx.zip> [--inbox record/inbox]

Manifest có caption chưa che: chỉ để ở máy (record/ đã nằm ngoài git), không gửi đi đâu.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}
MANIFEST = "fb_dyi_manifest.jsonl"


def fix_text(s: str) -> str:
    """Facebook ghi UTF-8 như thể từng byte là latin-1 ("Ä\x91" thay cho "đ"): đảo lại."""
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s  # đã đúng sẵn (hoặc có ký tự ngoài latin-1)


def _fix(obj):
    if isinstance(obj, str):
        return fix_text(obj)
    if isinstance(obj, list):
        return [_fix(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    return obj


def _medias(post: dict):
    """Các media trong một bài đăng: attachments[].data[].media."""
    for att in post.get("attachments") or []:
        for d in att.get("data") or []:
            m = d.get("media")
            if isinstance(m, dict) and m.get("uri"):
                yield m


def _post_text(post: dict) -> str:
    return " ".join(d["post"] for d in post.get("data") or [] if isinstance(d, dict) and d.get("post"))


def parse_entries(root: Path) -> dict[str, dict]:
    """uri video (tương đối gốc zip) -> {caption, timestamp, title}. Bài đăng thắng your_videos."""
    found: dict[str, dict] = {}

    def add(uri, caption, ts, title=""):
        if PurePosixPath(uri).suffix.lower() not in VIDEO_EXTS:
            return
        cur = found.get(uri, {})
        found[uri] = {"caption": caption or cur.get("caption", ""),
                      "timestamp": ts or cur.get("timestamp"),
                      "title": title or cur.get("title", "")}

    # your_videos trước, bài đăng sau: caption bài đăng ghi đè mô tả video
    for jf in sorted(root.rglob("*.json"), key=lambda f: (f.name.lower().startswith("your_posts"), f)):
        try:
            data = _fix(json.loads(jf.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        name = jf.name.lower()
        if "video" in name and isinstance(data, dict):  # your_videos.json: {"videos_v2": [...]}
            for v in next((x for x in data.values() if isinstance(x, list)), []):
                if isinstance(v, dict) and v.get("uri"):
                    add(v["uri"], v.get("description", ""), v.get("creation_timestamp"),
                        v.get("title", ""))
        if name.startswith("your_posts") and isinstance(data, list):
            for post in data:
                if not isinstance(post, dict):
                    continue
                for m in _medias(post):
                    add(m["uri"], _post_text(post) or m.get("description", ""),
                        post.get("timestamp") or m.get("creation_timestamp"), m.get("title", ""))
    return found


def _safe_extract(zf: zipfile.ZipFile, dest: Path, want) -> None:
    """Chỉ giải nén JSON và video, chặn đường dẫn thoát khỏi dest (zip slip)."""
    base = dest.resolve()
    for info in zf.infolist():
        if info.is_dir() or not want(info.filename):
            continue
        target = (dest / info.filename).resolve()
        if base not in target.parents:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out)


def import_zip(zip_path: Path, inbox: Path) -> list[dict]:
    """Chép video của một zip DYI vào inbox, ghi manifest. Trả các dòng manifest mới."""
    inbox.mkdir(parents=True, exist_ok=True)
    man_path = inbox / MANIFEST
    seen = set()
    if man_path.exists():
        seen = {(r["zip"], r["uri"]) for r in map(json.loads, man_path.read_text(
            encoding="utf-8").splitlines()) if r}
    rows: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="fbdyi_") as tmp, zipfile.ZipFile(zip_path) as zf:
        tmpd = Path(tmp)
        _safe_extract(zf, tmpd, lambda n: n.lower().endswith(".json"))
        entries = parse_entries(tmpd)
        # video không có trong JSON vẫn lấy (caption rỗng)
        for n in zf.namelist():
            if PurePosixPath(n).suffix.lower() in VIDEO_EXTS:
                entries.setdefault(n, {"caption": "", "timestamp": None, "title": ""})
        wanted = {u for u in entries if (zip_path.name, u) not in seen}
        _safe_extract(zf, tmpd, lambda n: n in wanted)
        for i, uri in enumerate(sorted(wanted, key=lambda u: (entries[u]["timestamp"] or 0, u))):
            src = tmpd / uri
            if not src.is_file():
                continue  # JSON nhắc tới nhưng zip không có tệp (bản xuất chia nhiều phần)
            e = entries[uri]
            ts = e["timestamp"]
            stamp = (datetime.fromtimestamp(ts, timezone.utc).strftime("%Y%m%d_%H%M%S")
                     if ts else "notime")
            stem = f"fb_{stamp}_{i}"
            dst = inbox / f"{stem}{src.suffix.lower()}"
            shutil.copy2(src, dst)
            rows.append({"zip": zip_path.name, "uri": uri, "file": dst.name, "stem": stem,
                         "caption": e["caption"], "title": e["title"], "timestamp": ts,
                         "source": "facebook-dyi"})
    with man_path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return rows


def import_inbox(inbox: Path) -> list[dict]:
    """Mọi facebook-*.zip trong inbox (zip đã nhập thì các video cũ được bỏ qua nhờ manifest)."""
    rows: list[dict] = []
    for z in sorted(inbox.glob("facebook-*.zip")):
        try:
            rows += import_zip(z, inbox)
        except zipfile.BadZipFile:
            print("zip hỏng, bỏ qua:", z.name)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip", nargs="?")
    ap.add_argument("--inbox", default=str(Path(__file__).resolve().parents[1] / "record" / "inbox"))
    a = ap.parse_args()
    inbox = Path(a.inbox)
    rows = import_zip(Path(a.zip), inbox) if a.zip else import_inbox(inbox)
    print(f"{len(rows)} video mới vào {inbox}")


if __name__ == "__main__":
    main()
