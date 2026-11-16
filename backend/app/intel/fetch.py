"""Tải HTML/tệp của trang nguồn (LI1, LI2) — lịch sự và không vượt rào.

Không cookie, không đăng nhập, không giải CAPTCHA. Mỗi host cách nhau ít nhất `delay_s`.
robots.txt đọc một lần cho mỗi host; không đọc được thì chỉ cho các URL danh sách đã cấu
hình. Trang tải được lưu thô dưới `data/cache/legal-intel/<ngày>/` để đối chiếu về sau.

LI2: anle.toaan.gov.vn là ứng dụng Oracle ADF (JavaScript) nên `Renderer` mở Chromium
headless để đọc. Chứng thư trung gian của GlobalSign mà site đó không gửi kèm nằm ở
`certs/`, nạp vào `ssl_context()` dùng chung cho mọi client httpx — không bao giờ tắt
kiểm tra chứng thư. Chromium tự lấy chứng thư trung gian qua AIA.
"""

from __future__ import annotations

import hashlib
import os
import ssl
import threading
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import certifi
import httpx
from loguru import logger

CACHE_ROOT = Path("/app/data/cache/legal-intel")
CERTS_DIR = Path(__file__).with_name("certs")
_ROBOTS_TIMEOUT = 15.0
BLOCKED_STATUS = {401, 403, 429}  # nơi gọi đánh dấu `blocked`, báo "cần lấy tay"
TOO_LARGE = 413  # tệp vượt `max_bytes`; nơi gọi đánh dấu `failed`

_SSL: ssl.SSLContext | None = None
_BROWSER_LOCK = threading.Lock()


def ssl_context() -> ssl.SSLContext:
    """Một context dùng chung: bundle certifi + mọi `*.pem` đã commit trong `certs/`."""
    global _SSL
    if _SSL is None:
        ctx = ssl.create_default_context(cafile=certifi.where())
        for pem in sorted(CERTS_DIR.glob("*.pem")):
            ctx.load_verify_locations(cafile=str(pem))
        _SSL = ctx
    return _SSL


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
        self._own_client = client is None
        self._client = client or httpx.Client(
            follow_redirects=True,
            timeout=30.0,
            headers={"User-Agent": user_agent},
            verify=ssl_context(),
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
            elif 400 <= resp.status_code < 500:
                # RFC 9309 §2.3.1.3: robots.txt 4xx (vd. anle trả 404) = không giới hạn gì
                parser.parse([])
            else:  # 5xx: thận trọng, chỉ cho URL danh sách đã cấu hình
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

    @property
    def can_render(self) -> bool:
        """Có được mở trình duyệt không: client tiêm vào (test/offline) thì không, vì
        trình duyệt không đi qua transport giả đó."""
        return self._own_client

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

    def get_bytes(self, url: str, *, max_bytes: int) -> tuple[int, bytes, str]:
        """Tải một tệp công khai (PDF/DOC…): `(status, body, content-type)`.

        Vượt `max_bytes` thì dừng giữa dòng và trả `TOO_LARGE`, không đọc tiếp.
        """
        if not self.allowed(url):
            logger.info("robots.txt không cho phép {} — không tải", url)
            return 0, b"", ""
        self._throttle(urlparse(url).netloc)
        try:
            with self._client.stream("GET", url) as resp:
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if resp.status_code != 200:
                    return resp.status_code, b"", ctype
                chunks: list[bytes] = []
                size = 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        return TOO_LARGE, b"", ctype
                    chunks.append(chunk)
                return 200, b"".join(chunks), ctype
        except Exception as exc:  # noqa: BLE001 — lỗi mạng: nơi gọi đánh dấu lỗi
            logger.warning("Lỗi tải tệp {}: {}", url, exc.__class__.__name__)
            return 0, b"", ""


class Renderer:
    """Chromium headless cho cả một lượt quét, đóng ở cuối lượt (LI2).

    Cùng luật robots/delay như `Fetcher`; `_BROWSER_LOCK` bảo đảm chỉ một trình duyệt chạy
    tại một thời điểm. Luôn `--disable-gpu`: GPU để dành cho Ollama.
    """

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._playwright = None
        self._browser = None

    def __enter__(self) -> Renderer:
        _BROWSER_LOCK.acquire()
        return self

    def __exit__(self, *exc_info: object) -> None:
        try:
            self.close()
        finally:
            _BROWSER_LOCK.release()

    def _open(self):
        if self._browser is None:
            from playwright.sync_api import sync_playwright

            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.launch(
                executable_path=os.getenv("PLAYWRIGHT_CHROMIUM_PATH") or None,
                headless=True,
                args=["--disable-gpu", "--no-sandbox"],
            )
        return self._browser

    def close(self) -> None:
        for closer in (
            getattr(self._browser, "close", None),
            getattr(self._playwright, "stop", None),
        ):
            if closer is not None:
                try:
                    closer()
                except Exception as exc:  # noqa: BLE001 — đóng hỏng cũng không được chặn lượt quét
                    logger.info("Đóng trình duyệt lỗi: {}", exc.__class__.__name__)
        self._browser = None
        self._playwright = None

    def render(self, url: str, timeout_ms: int = 60_000) -> str:
        """HTML sau khi JavaScript chạy; "" khi robots chặn hoặc trình duyệt lỗi."""
        if not self.fetcher.allowed(url):
            logger.info("robots.txt không cho phép {} — không render", url)
            return ""
        self.fetcher._throttle(urlparse(url).netloc)
        try:
            browser = self._open()
            page = browser.new_page(user_agent=self.fetcher.user_agent)
            try:
                page.goto(url, wait_until="load", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
                except Exception:  # noqa: BLE001 — trang còn gọi mạng nền: vẫn lấy HTML hiện có
                    pass
                html = page.content()
            finally:
                page.close()
        except Exception as exc:  # noqa: BLE001 — trình duyệt hỏng: coi như không đọc được
            logger.warning("Không render được {}: {}", url, exc.__class__.__name__)
            return ""
        self.fetcher._cache(url, html)
        return html
