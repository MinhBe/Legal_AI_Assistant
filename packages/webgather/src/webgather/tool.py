"""Agent-facing tool surface. An agent runtime (Claude, Codex, pi.dev) registers
one tool whose schema is TOOL_SCHEMA and whose handler is run_tool. The handler
returns plain JSON-able dicts, never raising, so the model always gets a result
it can read.

    from webgather.tool import TOOL_SCHEMA, run_tool
    result = run_tool({"action": "collect", "url": "https://x.gov.vn/faq/1"})
"""

from __future__ import annotations

from .compliance import ComplianceGate, Policy
from .pipeline import collect

TOOL_SCHEMA = {
    "name": "webgather",
    "description": (
        "Collect public web content under a compliance gate. It refuses, never "
        "bypasses: no login, no cookies, no CAPTCHA solving, no private groups or "
        "profiles. Returned text is de-identified. Use 'check' to preview a "
        "decision without fetching, 'collect' to fetch one URL."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["check", "collect"]},
            "url": {"type": "string", "description": "An http(s) URL."},
            "mask": {
                "type": "boolean",
                "default": True,
                "description": "De-identify the returned text (default true).",
            },
        },
        "required": ["action", "url"],
    },
}


def _gate(policy: Policy | None) -> ComplianceGate:
    return ComplianceGate(policy=policy)


def run_tool(args: dict, *, policy: Policy | None = None, masker=None) -> dict:
    action = args.get("action")
    url = args.get("url", "")
    if action not in ("check", "collect"):
        return {"ok": False, "error": f"unknown action {action!r}; use 'check' or 'collect'"}
    if not isinstance(url, str) or not url:
        return {"ok": False, "error": "missing 'url'"}

    gate = _gate(policy)
    if action == "check":
        d = gate.check(url)
        return {"ok": d.allowed, "decision": d.as_dict()}

    use_masker = masker if args.get("mask", True) else _Identity()
    rec = collect(url, gate=gate, masker=use_masker)
    out = {
        "ok": rec.ok,
        "decision": rec.decision.as_dict(),
        "url_hash": rec.url_hash,
    }
    if rec.ok:
        out.update({"title": rec.title, "text": rec.text, "fetched_at": rec.fetched_at})
    return out


class _Identity:
    def mask(self, text: str) -> str:
        return text
