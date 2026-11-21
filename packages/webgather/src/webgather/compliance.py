"""The compliance gate: decides, before any request, whether a URL may be fetched.

It refuses rather than works around. There is no branch anywhere that retries a
block with a fake user-agent, a proxy, a cookie or a solved CAPTCHA; those simply
do not exist in this package.

Order of checks for a URL:
    1. scheme / host sane
    2. source policy (per-host allow/deny paths, auth required)
    3. private-URL patterns (groups, profiles, messages)
    4. robots.txt (unless the policy marks the host as API/consented)
    5. rate limit (per-host minimum delay)

A response can still be blocked AFTER fetch by `inspect_response` when the body
or status reveals a login wall or CAPTCHA that the pre-check could not see.
"""

from __future__ import annotations

import re
import time
import urllib.robotparser
from dataclasses import dataclass, field
from urllib.parse import urlsplit

USER_AGENT = "webgather/0.1 (+compliant-collector; respects robots.txt)"

# Reason codes an agent can branch on.
ALLOW = "allow"
R_BAD_URL = "bad_url"
R_ROBOTS = "robots_disallow"
R_PRIVATE = "private_url"
R_TOS = "tos_denied"
R_AUTH = "auth_required"
R_LOGIN_WALL = "login_wall"
R_CAPTCHA = "captcha"
R_HTTP = "http_error"
R_RATE = "rate_limited"

# URL shapes that are private or personal by nature. Conservative on purpose:
# a public group still matches /groups/ and is refused unless a policy allowlists
# the exact host+path. Better to under-collect than to touch private data.
_PRIVATE_PATTERNS = [
    re.compile(r"facebook\.com/groups/", re.I),
    re.compile(r"facebook\.com/messages", re.I),
    re.compile(r"facebook\.com/profile\.php", re.I),
    re.compile(r"/messenger", re.I),
    re.compile(r"instagram\.com/(?:direct|stories)/", re.I),
    re.compile(r"/login", re.I),
    re.compile(r"/checkpoint", re.I),
]

# Markers in a fetched body that mean we hit a wall, not content.
_LOGIN_MARKERS = [
    "you must log in to continue",
    "bạn phải đăng nhập",
    "log into facebook",
    "đăng nhập vào facebook",
    'name="login"',
    "please log in",
]
_CAPTCHA_MARKERS = [
    "captcha",
    "g-recaptcha",
    "hcaptcha",
    "unusual traffic",
    "xác minh bạn không phải là robot",
    "are you a robot",
]


@dataclass
class Decision:
    allowed: bool
    reason: str = ALLOW
    detail: str = ""
    wait_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "detail": self.detail,
            "wait_seconds": round(self.wait_seconds, 2),
        }


@dataclass
class SourcePolicy:
    """Hand-written rule for one host, with its legal basis on one line."""

    host: str
    legal_basis: str  # e.g. "robots.txt cho phép; trang hỏi đáp công khai"
    auth: str = "none"  # none | api_key | user_upload
    min_delay: float = 5.0
    allow_paths: list[str] = field(default_factory=list)  # regex; empty = any
    deny_paths: list[str] = field(default_factory=list)  # regex
    check_robots: bool = True  # False for official APIs / consented uploads

    def path_ok(self, path: str) -> bool:
        if any(re.search(p, path) for p in self.deny_paths):
            return False
        if self.allow_paths:
            return any(re.search(p, path) for p in self.allow_paths)
        return True


class Policy:
    """A registry of SourcePolicy by host. Unknown hosts fall back to a cautious
    default (robots respected, 5s delay, no private paths)."""

    def __init__(self, policies: list[SourcePolicy] | None = None,
                 default_min_delay: float = 5.0,
                 allow_unknown_hosts: bool = True) -> None:
        self._by_host: dict[str, SourcePolicy] = {}
        self.default_min_delay = default_min_delay
        self.allow_unknown_hosts = allow_unknown_hosts
        for p in policies or []:
            self.add(p)

    def add(self, p: SourcePolicy) -> None:
        self._by_host[p.host.lower()] = p

    def for_host(self, host: str) -> SourcePolicy | None:
        host = host.lower()
        if host in self._by_host:
            return self._by_host[host]
        # match a parent domain policy (e.g. a policy on "gov.vn")
        for known, p in self._by_host.items():
            if host == known or host.endswith("." + known):
                return p
        return None


class ComplianceGate:
    def __init__(self, policy: Policy | None = None,
                 robots_loader=None) -> None:
        self.policy = policy or Policy()
        self._last_fetch: dict[str, float] = {}
        self._robots_cache: dict[str, urllib.robotparser.RobotFileParser] = {}
        # injectable so tests need no network
        self._robots_loader = robots_loader or self._load_robots

    # ---- pre-fetch -------------------------------------------------------
    def check(self, url: str) -> Decision:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return Decision(False, R_BAD_URL, f"not an http(s) url: {url!r}")

        host = parts.hostname or ""
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query

        if any(p.search(url) for p in _PRIVATE_PATTERNS):
            return Decision(False, R_PRIVATE,
                            "URL matches a private/personal pattern (group, profile, message or login)")

        pol = self.policy.for_host(host)
        if pol is None and not self.policy.allow_unknown_hosts:
            return Decision(False, R_TOS, f"no policy for host {host!r} and unknown hosts are not allowed")
        if pol is not None and not pol.path_ok(parts.path):
            return Decision(False, R_TOS, f"path denied by policy for {host!r}")

        check_robots = pol.check_robots if pol else True
        if check_robots:
            ok = self._robots_allows(parts.scheme, host, url)
            if ok is False:
                return Decision(False, R_ROBOTS, f"robots.txt disallows {path}")

        min_delay = pol.min_delay if pol else self.policy.default_min_delay
        wait = self._rate_wait(host, min_delay)
        if wait > 0:
            return Decision(False, R_RATE, f"min delay {min_delay}s not elapsed for {host}", wait_seconds=wait)

        return Decision(True, ALLOW, pol.legal_basis if pol else "unknown host; robots respected")

    def note_fetch(self, url: str) -> None:
        host = urlsplit(url).hostname or ""
        self._last_fetch[host] = time.monotonic()

    def min_delay_for(self, url: str) -> float:
        pol = self.policy.for_host(urlsplit(url).hostname or "")
        return pol.min_delay if pol else self.policy.default_min_delay

    # ---- post-fetch ------------------------------------------------------
    def inspect_response(self, status: int, body: str) -> Decision:
        if status in (401, 403):
            return Decision(False, R_LOGIN_WALL, f"HTTP {status}: access refused (likely login required)")
        if status == 429:
            return Decision(False, R_RATE, "HTTP 429: too many requests")
        if status >= 400:
            return Decision(False, R_HTTP, f"HTTP {status}")
        low = body.lower()
        if any(m in low for m in _CAPTCHA_MARKERS):
            return Decision(False, R_CAPTCHA, "response looks like a CAPTCHA / bot check")
        if any(m in low for m in _LOGIN_MARKERS):
            return Decision(False, R_LOGIN_WALL, "response is a login wall, not content")
        return Decision(True, ALLOW, "response looks like content")

    # ---- internals -------------------------------------------------------
    def _rate_wait(self, host: str, min_delay: float) -> float:
        last = self._last_fetch.get(host)
        if last is None:
            return 0.0
        elapsed = time.monotonic() - last
        return max(0.0, min_delay - elapsed)

    def _robots_allows(self, scheme: str, host: str, url: str) -> bool | None:
        rp = self._robots_cache.get(host)
        if rp is None:
            rp = self._robots_loader(f"{scheme}://{host}/robots.txt")
            self._robots_cache[host] = rp
        if rp is None:
            return None  # could not load; treat as unknown, do not block
        try:
            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return None

    @staticmethod
    def _load_robots(robots_url: str):
        import urllib.request

        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 (http(s) only)
                text = resp.read().decode("utf-8", "replace")
            rp.parse(text.splitlines())
            return rp
        except Exception:
            return None
