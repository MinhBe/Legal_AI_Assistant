"""A source for content the user supplied themselves with consent: a Facebook
"Download Your Information" export, a screenshot's OCR text, a pasted link's
page. There is nothing to fetch behind a login, because the user already holds
the data. `plan` yields file:// paths or public URLs the user chose; the gate
passes local files through and still screens any public URL.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


class UserUpload:
    name = "user-upload"
    auth = "user_upload"

    def __init__(self, paths: list[str] | None = None, consent: bool = False) -> None:
        if not consent:
            raise ValueError("user-upload requires explicit consent=True (the user must agree to share)")
        self.paths = paths or []

    def plan(self, query: str | None = None) -> Iterable[str]:
        for p in self.paths:
            if p.startswith(("http://", "https://", "file://")):
                yield p
            else:
                yield Path(p).resolve().as_uri()
