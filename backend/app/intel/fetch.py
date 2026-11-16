"""Tải HTML của trang nguồn (LI1) — lịch sự và không vượt rào.

Không cookie, không đăng nhập, không giải CAPTCHA. Mỗi host cách nhau ít nhất `delay_s`.
robots.txt đọc một lần cho mỗi host; không đọc được thì chỉ cho các URL danh sách đã cấu
hình. Trang tải được lưu thô dưới `data/cache/legal-intel/<ngày>/` để đối chiếu về sau.
"""

from __future__ import annotations

import hashlib
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from loguru import logger

CACHE_ROOT = Path("/app/data/cache/legal-intel")
_ROBOTS_TIMEOUT = 15.0
BLOCKED_STATUS = {401, 403, 429}  # nơi gọi đánh dấu `blocked`, báo "cần lấy tay"


class Fetcher:
    """GET một URL cho mỗi host. `get` trả `(status, text)`; status 0 = không gửi được
    yêu cầu (robots chặn hoặc lỗi mạng)."""

    def __init__(
        self,
        user_agent: str,
        delay_s: float = 5.0,
        *,
        client: httpx.Client | None = None,
        cache_root: Path | None = None,
        allowed_urls: tuple[str, ...] = (),
    ) -> None:
        self.user_agent = user_agent
        self.delay_s = float(delay_s)
        self._client = client or httpx.Client(
            follow_redirects=True, timeout=30.0, headers={"User-Agent": user_agent}
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._last: dict[str, float] = {}
        self._cache_root = Path(cache_root or CACHE_ROOT)
        self._allowed = set(allowed_urls)

    # ---- robots.txt ----
    def _robots_for(self, root: str) -> RobotFileParser | None:
        """Parser robots của host, cache theo host; None = không đọc được."""
        if root in self._robots:
            return self._robots[root]
        parser: RobotFileParser | None = RobotFileParser()
        try:
            resp = self._client.get(f"{root}/robots.txt", timeout=_ROBOTS_TIMEOUT)
            if resp.status_code == 200:
                parser.parse(resp.text.splitlines())
            else:
                parser = None
        except Exception as exc:  # noqa: BLE001 — mạng hỏng thì coi như không có robots
            logger.info("Không đọc được robots.txt của {}: {}", root, exc.__class__.__name__)
            parser = None
        self._robots[root] = parser
        return parser

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        parser = self._robots_for(f"{parts.scheme}://{parts.netloc}")
        if parser is None:  # không đọc được robots: chỉ cho URL danh sách đã cấu hình
            return url in self._allowed
        return parser.can_fetch(self.user_agent, url)

    # ---- tải ----
    def _throttle(self, host: str) -> None:
        last = self._last.get(host)
        if last is not None:
            wait = self.delay_s - (time.monotonic() - last)
            if wait > 0:
                time.sleep(wait)
        self._last[host] = time.monotonic()

    def _cache(self, url: str, text: str) -> None:
        name = f"{urlparse(url).netloc}_{hashlib.sha1(url.encode()).hexdigest()[:12]}.html"
        path = self._cache_root / date.today().isoformat() / name
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError as exc:  # hết chỗ / quyền: chỉ mất bản lưu, không hỏng lượt quét
            logger.warning("Không lưu được bản thô {}: {}", path, exc)

    def get(self, url: str) -> tuple[int, str]:
        if not self.allowed(url):
            logger.info("robots.txt không cho phép {} — không tải", url)
            return 0, ""
        self._throttle(urlparse(url).netloc)
        try:
            resp = self._client.get(url)
        except Exception as exc:  # noqa: BLE001 — lỗi mạng: nơi gọi đánh dấu lỗi nguồn
            logger.warning("Lỗi tải {}: {}", url, exc.__class__.__name__)
            return 0, ""
        if resp.status_code == 200:
            self._cache(url, resp.text)
        return resp.status_code, resp.text
