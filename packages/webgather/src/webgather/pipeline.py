"""The one call an agent makes: collect(url). Wires the gate, the fetcher and the
masker together and returns a Record. Never raises on a blocked URL; it returns a
Record with ok=False and the decision, so an agent can branch on `r.decision.reason`.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from .compliance import ComplianceGate, Decision, R_RATE
from .core import Record
from .fetch import RawResponse, extract_title, fetch, html_to_text, url_hash
from .pii import Masker, VietnamesePiiMasker


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect(
    url: str,
    *,
    gate: ComplianceGate | None = None,
    masker: Masker | None = None,
    source: str = "public-html",
    wait_on_rate_limit: bool = True,
    max_wait: float = 30.0,
    fetcher=fetch,
    api_key_header: tuple[str, str] | None = None,
) -> Record:
    """Gate -> fetch -> inspect -> de-identify. `fetcher` is injectable for tests."""
    gate = gate or ComplianceGate()
    masker = masker or VietnamesePiiMasker()

    decision = gate.check(url)
    if not decision.allowed and decision.reason == R_RATE and wait_on_rate_limit:
        if decision.wait_seconds <= max_wait:
            time.sleep(decision.wait_seconds)
            decision = gate.check(url)
    if not decision.allowed:
        return Record(url=url, ok=False, decision=decision, source=source, url_hash=url_hash(url))

    resp: RawResponse = fetcher(url, api_key_header=api_key_header)
    gate.note_fetch(url)

    if resp.status == 0:
        return Record(url=url, ok=False,
                      decision=Decision(False, "http_error", resp.body),
                      source=source, url_hash=url_hash(url))

    verdict = gate.inspect_response(resp.status, resp.body)
    if not verdict.allowed:
        return Record(url=url, ok=False, decision=verdict, source=source, url_hash=url_hash(url))

    title = masker.mask(extract_title(resp.body))
    text = masker.mask(html_to_text(resp.body))
    return Record(
        url=url,
        ok=True,
        decision=verdict,
        source=source,
        title=title,
        text=text,
        fetched_at=_now(),
        url_hash=url_hash(url),
    )
