"""Facebook "Download Your Information" export (JSON) of Minh's OWN account.

Facebook writes UTF-8 as if each byte were latin-1 ("Ä\x91" for "đ"); `fix_text` reverses it.
Only JSON members and referenced video members are read; zip-slip paths are refused.
"""

from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from ..core import Item, stem_for

VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".m4v"}


def fix_text(s):
    if not isinstance(s, str):
        return s
    try:
        return s.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return s


def _fix(obj):
    if isinstance(obj, str):
        return fix_text(obj)
    if isinstance(obj, list):
        return [_fix(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _fix(v) for k, v in obj.items()}
    return obj


def _medias(post: dict):
    for att in post.get("attachments") or []:
        for d in att.get("data") or []:
            m = d.get("media")
            if isinstance(m, dict) and m.get("uri"):
                yield m


def _post_text(post: dict) -> str:
    return " ".join(d["post"] for d in post.get("data") or [] if isinstance(d, dict) and d.get("post"))


def parse_entries(zf: zipfile.ZipFile) -> dict[str, dict]:
    """video uri -> {caption, timestamp, title}. your_videos first, posts override the caption."""
    found: dict[str, dict] = {}

    def add(uri, caption, ts, title=""):
        if PurePosixPath(uri).suffix.lower() not in VIDEO_EXTS:
            return
        cur = found.get(uri, {})
        found[uri] = {"caption": caption or cur.get("caption", ""),
                      "timestamp": ts or cur.get("timestamp"),
                      "title": title or cur.get("title", "")}

    names = [n for n in zf.namelist() if n.lower().endswith(".json")]
    for n in sorted(names, key=lambda x: (PurePosixPath(x).name.lower().startswith("your_posts"), x)):
        try:
            data = _fix(json.loads(zf.read(n).decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        base = PurePosixPath(n).name.lower()
        if "video" in base and isinstance(data, dict):
            for v in next((x for x in data.values() if isinstance(x, list)), []):
                if isinstance(v, dict) and v.get("uri"):
                    add(v["uri"], v.get("description", ""), v.get("creation_timestamp"),
                        v.get("title", ""))
        if base.startswith("your_posts") and isinstance(data, list):
            for post in data:
                if isinstance(post, dict):
                    for m in _medias(post):
                        add(m["uri"], _post_text(post) or m.get("description", ""),
                            post.get("timestamp") or m.get("creation_timestamp"), m.get("title", ""))
    members = set(zf.namelist())
    for n in members:  # videos with no JSON entry still count
        if PurePosixPath(n).suffix.lower() in VIDEO_EXTS:
            found.setdefault(n, {"caption": "", "timestamp": None, "title": ""})
    return {u: e for u, e in found.items() if u in members and _inside(u)}


def _inside(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts


class FacebookDYI:
    name = "fb-dyi"

    def __init__(self, path: str, pattern: str = "facebook-*.zip") -> None:
        p = Path(path)
        self.zips = [p] if p.is_file() else sorted(p.glob(pattern))

    def list_items(self, since=None):
        for z in self.zips:
            try:
                zf = zipfile.ZipFile(z)
            except zipfile.BadZipFile:
                continue
            with zf:
                for uri, e in sorted(parse_entries(zf).items()):
                    ts = e["timestamp"]
                    yield Item(id=f"{z.stem}:{uri}", source="facebook-dyi", consent="own",
                               url=f"{z}!{uri}", caption=e["caption"], title=e["title"],
                               posted_at=datetime.fromtimestamp(ts, timezone.utc).isoformat()
                               if ts else None)

    def fetch(self, item: Item, out_dir: Path) -> Path:
        zpath, uri = item.url.split("!", 1)
        dst = Path(out_dir) / f"{stem_for(item)}{PurePosixPath(uri).suffix.lower()}"
        with zipfile.ZipFile(zpath) as zf, zf.open(uri) as src, dst.open("wb") as out:
            shutil.copyfileobj(src, out)
        return dst
