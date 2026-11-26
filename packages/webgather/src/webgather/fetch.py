"""A minimal, stdlib-only fetcher and HTML-to-text, so the core installs with
nothing. It sends no cookies and no auth beyond an explicit API key header the
caller passes. It does not follow redirects into other hosts silently; a 3xx to
a login host surfaces as a login wall via the gate's response inspection.
"""

from __future__ import annotations

import gzip
import hashlib
import html
import re
import urllib.request
from dataclasses import dataclass

from .compliance import USER_AGENT


@dataclass
class RawResponse:
    status: int
    body: str
    final_url: str


def fetch(url: str, timeout: int = 20, api_key_header: tuple[str, str] | None = None) -> RawResponse:
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if api_key_header:
        headers[api_key_header[0]] = api_key_header[1]
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (http(s) only via gate)
            raw = resp.read()
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            charset = resp.headers.get_content_charset() or "utf-8"
            body = raw.decode(charset, "replace")
            return RawResponse(resp.status, body, resp.geturl())
    except urllib.error.HTTPError as e:  # noqa: PERF203
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        return RawResponse(e.code, body, url)
    except Exception as e:
        return RawResponse(0, f"__fetch_error__: {e}", url)


_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.I | re.S)
_WS = re.compile(r"[ \t]+")
_BLANK = re.compile(r"\n{3,}")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def html_to_text(doc: str) -> str:
    doc = _SCRIPT.sub(" ", doc)
    doc = re.sub(r"</(p|div|li|br|h[1-6]|tr|title)>", "\n", doc, flags=re.I)
    doc = _TAG.sub(" ", doc)
    doc = html.unescape(doc)
    doc = _WS.sub(" ", doc)
    doc = _BLANK.sub("\n\n", doc)
    return "\n".join(line.strip() for line in doc.splitlines()).strip()


def extract_title(doc: str) -> str:
    m = _TITLE.search(doc)
    return html.unescape(_TAG.sub("", m.group(1)).strip()) if m else ""


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
