"""CLI: `webgather check <url>` and `webgather collect <url>`.

Output is JSON on stdout so a pi.dev / shell agent can parse it. Exit code is 0
when allowed/ok, 2 when the gate blocked, 1 on a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys

from .tool import run_tool


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="webgather", description="Compliance-first web collection.")
    sub = ap.add_subparsers(dest="action", required=True)
    for name, help_ in (("check", "preview the gate decision, fetch nothing"),
                        ("collect", "fetch one URL and return de-identified text")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("url")
        if name == "collect":
            p.add_argument("--no-mask", action="store_true", help="return raw text (not de-identified)")

    args = ap.parse_args(argv)
    payload = {"action": args.action, "url": args.url}
    if args.action == "collect":
        payload["mask"] = not args.no_mask

    result = run_tool(payload)
    json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if "error" in result:
        return 1
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    raise SystemExit(main())
