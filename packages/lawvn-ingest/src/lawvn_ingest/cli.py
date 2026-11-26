"""lawvn-ingest CLI. Output is JSON on stdout (one object) so agents can parse it.

    lawvn-ingest adapters
    lawvn-ingest list  --adapter fb-dyi --opt path=record/inbox [--since 2026-01-01]
    lawvn-ingest fetch --adapter folder --opt path=D:/clips --opt consent=licensed --out record/inbox
    lawvn-ingest fetch ... --dry-run
    lawvn-ingest push  [--collect]        # Legal Agentic: Kaggle ASR -> PII, or download masked results
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .core import adapters, get_adapter, ingest


def _opts(pairs: list[str]) -> dict:
    out = {}
    for p in pairs:
        k, sep, v = p.partition("=")
        if not sep:
            raise SystemExit(f"--opt needs key=value, got {p!r}")
        out[k] = v
    return out


def _print(obj) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, indent=1) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lawvn-ingest")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("adapters")
    for name in ("list", "fetch"):
        s = sub.add_parser(name)
        s.add_argument("--adapter", required=True)
        s.add_argument("--opt", action="append", default=[], help="adapter option key=value")
        s.add_argument("--since")
        if name == "fetch":
            s.add_argument("--out", help="default: <repo Legal Agentic>/record/inbox")
            s.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("push")
    p.add_argument("--collect", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "adapters":
        _print(sorted(adapters()))
        return 0
    if a.cmd == "push":
        from .pipeline import run_inbox

        return run_inbox(collect=a.collect)
    ad = get_adapter(a.adapter, **_opts(a.opt))
    if a.cmd == "list":
        from dataclasses import asdict

        _print([asdict(i) for i in ad.list_items(a.since)])
        return 0
    if a.out:
        out = Path(a.out)
    else:
        from .pipeline import inbox

        out = inbox()
    rows = ingest(ad, out, since=a.since, dry_run=a.dry_run)
    _print({"out": str(out), "dry_run": a.dry_run, "new": len(rows), "items": rows})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
