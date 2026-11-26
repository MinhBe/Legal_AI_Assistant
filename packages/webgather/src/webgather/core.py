"""Contract: the Record an agent gets back, the Source protocol, and the registry.

Decoupled from any product: webgather knows nothing about LawVN. A product wires
its own PII masker and its own source policies in; the core only defines shapes.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .compliance import Decision

GROUP = "webgather.sources"

# How a source is allowed to authenticate. There is deliberately no "cookie",
# "session" or "password" value: the gate rejects anything outside this set, so
# no adapter can borrow a logged-in session.
AUTH = frozenset({"none", "api_key", "user_upload"})


@dataclass
class Record:
    """What a collection returns. `text` is already de-identified when `ok`."""

    url: str
    ok: bool
    decision: "Decision"
    source: str = ""
    title: str = ""
    text: str = ""
    fetched_at: str | None = None  # ISO 8601 UTC
    # Hash of the origin URL, never the raw URL of a personal post, so a record
    # can be de-duplicated and removed on request without storing the address.
    url_hash: str = ""
    lang: str = ""
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        from dataclasses import asdict

        d = asdict(self)
        d["decision"] = self.decision.as_dict()
        return d


@runtime_checkable
class Source(Protocol):
    """An adapter for one kind of origin (a public site, a user upload, an API).

    `auth` must be one of AUTH. `plan` yields the URLs the source wants to fetch;
    the pipeline runs each through the gate before fetching, so a Source never
    fetches on its own.
    """

    name: str
    auth: str

    def plan(self, query: str | None = None) -> Iterable[str]: ...


def _builtins() -> dict[str, type]:
    from .adapters.public_html import PublicHtml
    from .adapters.user_upload import UserUpload

    return {a.name: a for a in (PublicHtml, UserUpload)}


def sources() -> dict[str, type]:
    """Built-ins plus every class registered under the `webgather.sources` group."""
    found = _builtins()
    for ep in entry_points(group=GROUP):
        if ep.name not in found:
            found[ep.name] = ep.load()
    return found


def get_source(name: str, **opts) -> Source:
    reg = sources()
    if name not in reg:
        raise KeyError(f"unknown source {name!r}; have: {', '.join(sorted(reg))}")
    src = reg[name](**opts)
    if getattr(src, "auth", None) not in AUTH:
        raise ValueError(
            f"source {name!r} declares auth={getattr(src, 'auth', None)!r}; "
            f"allowed: {sorted(AUTH)} (no cookie/session/password)"
        )
    return src
