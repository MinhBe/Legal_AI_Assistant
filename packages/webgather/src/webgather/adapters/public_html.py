"""A source for public pages reachable without login. It only plans the URLs it
is given; the gate still decides each one. `auth` is always "none"; this adapter
has no field for a cookie or a password."""

from __future__ import annotations

from collections.abc import Iterable


class PublicHtml:
    name = "public-html"
    auth = "none"

    def __init__(self, urls: list[str] | None = None) -> None:
        self.urls = urls or []

    def plan(self, query: str | None = None) -> Iterable[str]:
        yield from self.urls
