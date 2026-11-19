"""LawVN side: put items into record/inbox and hand off to the Kaggle ASR -> Kaggle PII path.

The heavy work never runs on the home PC: tools/record_inbox.py versions the Kaggle dataset,
pushes the ASR and PII kernels, and `collect` downloads only the masked transcripts.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .core import get_adapter, ingest


def lawvn_root(start: Path | None = None) -> Path:
    env = os.environ.get("LAWVN_ROOT")
    if env:
        return Path(env)
    for p in [start or Path.cwd(), *(start or Path.cwd()).parents]:
        if (p / "tools" / "record_inbox.py").exists():
            return p
    raise FileNotFoundError("LawVN repo not found: set LAWVN_ROOT")


def inbox(root: Path | None = None) -> Path:
    return (root or lawvn_root()) / "record" / "inbox"


def enqueue(adapter: str, since: str | None = None, push: bool = False,
            root: Path | None = None, **opts) -> list[dict]:
    """Fetch new items of `adapter` into record/inbox. With push=True, also run
    tools/record_inbox.py (Kaggle ASR -> PII -> masked transcripts back)."""
    root = root or lawvn_root()
    rows = ingest(get_adapter(adapter, **opts), inbox(root), since=since)
    if push and rows:
        run_inbox(root)
    return rows


def run_inbox(root: Path | None = None, collect: bool = False) -> int:
    root = root or lawvn_root()
    cmd = [sys.executable, "-X", "utf8", str(root / "tools" / "record_inbox.py")]
    return subprocess.call(cmd + (["--collect"] if collect else []), cwd=root)
