"""Contract: Item, Adapter, the adapter registry and the store (inbox + sidecar + manifest)."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol, runtime_checkable

GROUP = "lawvn_ingest.adapters"
CONSENT = frozenset({"own", "licensed", "public-official"})
MANIFEST = "manifest.jsonl"


@dataclass(frozen=True)
class Item:
    """One media item an adapter can fetch. `consent` is mandatory and checked by the store."""

    id: str
    source: str
    consent: str  # "own" | "licensed" | "public-official"
    url: str = ""
    posted_at: str | None = None  # ISO 8601
    caption: str = ""
    media_type: str = "video"  # video | audio | text
    title: str = ""
    extra: dict = field(default_factory=dict)


@runtime_checkable
class Adapter(Protocol):
    name: str

    def list_items(self, since: str | None = None) -> Iterable[Item]: ...

    def fetch(self, item: Item, out_dir: Path) -> Path: ...


def _builtins() -> dict[str, type]:
    from .adapters.fb_dyi import FacebookDYI
    from .adapters.fb_graph import FacebookGraph
    from .adapters.folder import Folder

    return {a.name: a for a in (Folder, FacebookDYI, FacebookGraph)}


def adapters() -> dict[str, type]:
    """Built-ins plus every class registered under the `lawvn_ingest.adapters` entry-point group.

    A third-party package registers itself in its own pyproject, no edit here:
        [project.entry-points."lawvn_ingest.adapters"]
        my-source = "my_pkg.adapter:MyAdapter"
    """
    found = _builtins()
    for ep in entry_points(group=GROUP):
        if ep.name not in found:
            found[ep.name] = ep.load()
    return found


def get_adapter(name: str, **opts) -> Adapter:
    reg = adapters()
    if name not in reg:
        raise KeyError(f"unknown adapter {name!r}; have: {', '.join(sorted(reg))}")
    return reg[name](**opts)


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_")[:80] or "x"


def stem_for(item: Item) -> str:
    """File stem used in the inbox (and therefore as the ASR/PII stem downstream)."""
    return f"{_safe(item.source)}_{_safe(item.id)}"


class Store:
    """Output contract. For each fetched item, in `out_dir`:
    - the media file `<stem><ext>`;
    - a sidecar `<stem><ext>.meta.json` holding the Item;
    - one line appended to `manifest.jsonl`.
    Dedupe key: (source, id)."""

    def __init__(self, out_dir: Path) -> None:
        self.out = Path(out_dir)
        self.manifest = self.out / MANIFEST

    def seen(self) -> set[tuple[str, str]]:
        if not self.manifest.exists():
            return set()
        rows = (json.loads(x) for x in self.manifest.read_text(encoding="utf-8").splitlines() if x)
        return {(r["source"], r["id"]) for r in rows}

    def record(self, item: Item, path: Path) -> dict:
        row = {**asdict(item), "file": path.name}
        (path.parent / f"{path.name}.meta.json").write_text(
            json.dumps(row, ensure_ascii=False, indent=1), encoding="utf-8")
        with self.manifest.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row


def ingest(adapter: Adapter, out_dir: Path, since: str | None = None,
           dry_run: bool = False) -> list[dict]:
    """List, filter (consent, since, dedupe), fetch and record. Returns new manifest rows
    (in dry-run: the rows that would be written, without `file`)."""
    store = Store(out_dir)
    store.out.mkdir(parents=True, exist_ok=True)
    seen = store.seen()
    rows = []
    for item in adapter.list_items(since):
        if item.consent not in CONSENT:
            raise ValueError(f"{adapter.name}:{item.id}: consent {item.consent!r} not in {sorted(CONSENT)}")
        if (item.source, item.id) in seen:
            continue
        if since and item.posted_at and item.posted_at < since:
            continue
        seen.add((item.source, item.id))
        if dry_run:
            rows.append(asdict(item))
            continue
        rows.append(store.record(item, adapter.fetch(item, store.out)))
    return rows
