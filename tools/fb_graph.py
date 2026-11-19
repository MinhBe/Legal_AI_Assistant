"""Lấy video từ CHÍNH tài khoản Facebook của Minh qua Graph API chính thức -> record/inbox.

Minh 19/11/2026: cần một cách tự động lấy dữ liệu Facebook của chính mình. Không cào HTML, không
dùng cookie: app Meta của Minh ở chế độ Development, Minh là admin nên tự cấp được quyền
user_videos / user_posts cho chính mình mà không cần App Review.

Minh tự làm một lần (Claude không nhập token hộ):
  1. developers.facebook.com -> Tạo app (loại "Other"/"Consumer"), để chế độ Development.
  2. Graph API Explorer -> chọn app -> Get User Access Token, tick user_videos, user_posts.
  3. (khuyên) đổi sang token dài hạn ~60 ngày ở Access Token Debugger -> "Extend".
  4. Dán token vào RAG\\RAG\\keys\\facebook_user_token.txt (một dòng).

    python -X utf8 tools/fb_graph.py            # tải video mới vào record/inbox
    python -X utf8 tools/fb_graph.py --dry-run  # chỉ liệt kê, không tải

Sau đó tools/record_inbox.py đẩy lên Kaggle ASR -> che PII như mọi tệp khác.
Token chỉ đọc từ tệp và chỉ gửi tới graph.facebook.com; không in, không ghi log.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
TOKEN_FILE = ROOT / "keys" / "facebook_user_token.txt"
INBOX = ROOT / "record" / "inbox"
MANIFEST = "fb_graph_manifest.jsonl"
API = "https://graph.facebook.com/v23.0"
FIELDS = "id,title,description,created_time,length,source,permalink_url"


def list_videos(session, token: str, limit: int = 50):
    """Video Minh tự đăng (type=uploaded), lần theo paging.next."""
    url = f"{API}/me/videos"
    params = {"type": "uploaded", "fields": FIELDS, "limit": limit, "access_token": token}
    while url:
        r = session.get(url, params=params, timeout=60)
        if r.status_code != 200:
            err = r.json().get("error", {}) if r.headers.get("content-type", "").startswith(
                "application/json") else {}
            raise RuntimeError(f"Graph API {r.status_code}: {err.get('message', r.text[:200])}")
        body = r.json()
        yield from body.get("data", [])
        url = body.get("paging", {}).get("next")
        params = None  # next đã chứa sẵn mọi tham số


def stem_for(v: dict) -> str:
    t = datetime.strptime(v["created_time"], "%Y-%m-%dT%H:%M:%S%z").strftime("%Y%m%d_%H%M%S")
    return f"fbg_{t}_{v['id']}"


def fetch(session, token: str, inbox: Path, dry_run: bool = False) -> list[dict]:
    inbox.mkdir(parents=True, exist_ok=True)
    man = inbox / MANIFEST
    seen = {json.loads(x)["id"] for x in man.read_text(encoding="utf-8").splitlines() if x} \
        if man.exists() else set()
    rows = []
    for v in list_videos(session, token):
        if v["id"] in seen:
            continue
        row = {"id": v["id"], "stem": stem_for(v), "file": f"{stem_for(v)}.mp4",
               "caption": v.get("description", ""), "title": v.get("title", ""),
               "created_time": v["created_time"], "length_s": v.get("length"),
               "permalink": v.get("permalink_url"), "source": "facebook-graph"}
        if not v.get("source"):
            print("không có link tải (video không thuộc quyền sở hữu?), bỏ qua:", v["id"])
            continue
        if not dry_run:
            dst = inbox / row["file"]
            with session.get(v["source"], stream=True, timeout=600) as r:
                r.raise_for_status()
                with dst.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            with man.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        rows.append(row)
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not TOKEN_FILE.exists():
        raise SystemExit(f"chưa có token: đặt token vào {TOKEN_FILE} (xem đầu tệp này)")
    token = TOKEN_FILE.read_text(encoding="utf-8").strip()
    rows = fetch(requests.Session(), token, INBOX, a.dry_run)
    for r in rows:
        print(r["file"], r["created_time"], (r["caption"] or "")[:60].replace("\n", " "))
    print(f"{len(rows)} video {'(chưa tải, dry-run)' if a.dry_run else 'mới vào ' + str(INBOX)}")


if __name__ == "__main__":
    main()
