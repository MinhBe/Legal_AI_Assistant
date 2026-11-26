"""webgather: lightweight, compliance-first web collection for coding agents.

The core is stdlib-only. The flow is always the same:

    Source -> compliance gate -> fetch -> de-identify -> Record

The gate decides BEFORE any request whether a URL may be fetched, and refuses
(never works around) a login wall, a CAPTCHA, a disallowed robots rule, a
private URL or a rate limit. De-identification strips author identity at the
door, so personal data never lands in the store.

Entry points for an agent:
    from webgather import collect
    r = collect("https://example.gov.vn/faq/123")
    if r.ok:
        print(r.text)        # de-identified
    else:
        print(r.decision.reason)
"""

from __future__ import annotations

from .compliance import ComplianceGate, Decision, Policy, SourcePolicy
from .core import Record, Source, get_source, sources
from .pii import Masker, VietnamesePiiMasker
from .pipeline import collect

__all__ = [
    "collect",
    "Record",
    "Source",
    "sources",
    "get_source",
    "ComplianceGate",
    "Decision",
    "Policy",
    "SourcePolicy",
    "Masker",
    "VietnamesePiiMasker",
]

__version__ = "0.1.0"
