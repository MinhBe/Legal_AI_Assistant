"""Plain files from a folder (media Minh obtained himself, with the consent he declares)."""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..core import Item, stem_for

MEDIA = {".mp4": "video", ".mov": "video", ".mkv": "video", ".webm": "video", ".m4v": "video",
         ".m4a": "audio", ".mp3": "audio", ".wav": "audio", ".aac": "audio", ".ogg": "audio"}


class Folder:
    name = "folder"

    def __init__(self, path: str, consent: str = "own", source: str = "folder") -> None:
        self.path, self.consent, self.source = Path(path), consent, source

    def list_items(self, since=None):
        for p in sorted(self.path.iterdir()):
            if p.suffix.lower() not in MEDIA or not p.is_file():
                continue
            st = p.stat()
            yield Item(id=hashlib.sha1(f"{p.name}:{st.st_size}".encode()).hexdigest()[:16],
                       source=self.source, consent=self.consent, url=str(p), title=p.stem,
                       posted_at=datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(),
                       media_type=MEDIA[p.suffix.lower()])

    def fetch(self, item: Item, out_dir: Path) -> Path:
        src = Path(item.url)
        dst = Path(out_dir) / f"{stem_for(item)}{src.suffix.lower()}"
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        return dst
