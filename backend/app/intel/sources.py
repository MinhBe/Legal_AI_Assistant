"""Bộ đọc danh sách văn bản mới của từng trang nguồn (LI1).

Mỗi adapter: `name`, `listing_urls`, `last_status`, `parse(html, base_url) -> list[dict]`.
Chỉ đọc thẻ `<a>` bằng `html.parser` (không regex trên cả trang), nên trang đổi bố cục chỉ
hỏng phần đọc danh sách chứ không sinh dữ liệu rác.

Sự thật đo được ngày 2026-11-16 (fixture trong `data/fixtures/legal-intel/2026-11-16/`):
- thuvienphapluat.vn: robots cho phép tất cả; trang chủ liệt kê văn bản mới, loại văn bản
  nằm trong đường dẫn (`/van-ban/Lao-dong-Tien-luong/...`). Trang chi tiết trả HTTP 403 cho
  bot — không thử lại, đánh dấu `blocked` và báo "cần lấy tay".
- luatvietnam.vn: robots.txt cấm `/tim-van-ban.html?Keywords=*` và trang tìm kiếm (không dùng);
  `/van-ban-moi.html` liệt kê văn bản mới, link tương đối kết thúc `-d1.html`, `-d2.html`...
- anle.toaan.gov.vn: ứng dụng Oracle ADF (JavaScript) — HTTP thường chỉ trả về loader, cần
  trình duyệt headless. Chưa cài Playwright (Minh chưa duyệt) nên adapter trả 0 item,
  `last_status = "needs_browser"`.
"""

from __future__ import annotations

import re
from datetime import date
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

# Từ khoá nhận diện tin liên quan lao động (tiêu đề + loại/đường dẫn).
LABOR_KEYWORDS = (
    "lao động",
    "tiền lương",
    "việc làm",
    "bảo hiểm xã hội",
    "bhxh",
    "bảo hiểm thất nghiệp",
    "công đoàn",
    "an toàn vệ sinh lao động",
    "người lao động",
    "viên chức",
    "lao-dong-tien-luong",
    "bao-hiem",
    "án lệ",
)

# Số hiệu: "399/2026/NĐ-CP", "113/2026/VBHN-TT-BNNMT" (có năm) rồi "11636/VPCP-KGVX" (không năm).
_NUMBER_WITH_YEAR = re.compile(r"(\d{1,6}/\d{4}/[A-ZĐ][A-ZĐ0-9]*(?:-[A-ZĐ0-9]+)*)", re.IGNORECASE)
_NUMBER_PLAIN = re.compile(r"(\d{1,6}/[A-ZĐ][A-ZĐ0-9]*(?:-[A-ZĐ0-9]+)*)", re.IGNORECASE)
# Số hiệu chỉ có trong đường dẫn: "...-so-59-2020-qh14-186272-d1.html"
_NUMBER_IN_SLUG = re.compile(r"-so-(\d{1,6})-(\d{4})-([a-zA-Z]{2,4}\d{0,3})(?:-|$)")
_DATE_SHOWN = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

_KINDS = (
    ("Dự thảo", "Dự thảo"),
    ("Nghị định", "Nghị định"),
    ("Thông tư", "Thông tư"),
    ("Quyết định", "Quyết định"),
    ("Công văn", "Công văn"),
    ("Kế hoạch", "Kế hoạch"),
    ("Văn bản hợp nhất", "Văn bản hợp nhất"),
    ("Nghị quyết", "Nghị quyết"),
    ("Án lệ", "Án lệ"),
    ("Bộ luật", "Luật"),
    ("Luật", "Luật"),
)
_KIND_SLUGS = (
    ("van-ban-hop-nhat", "Văn bản hợp nhất"),
    ("nghi-dinh", "Nghị định"),
    ("thong-tu", "Thông tư"),
    ("quyet-dinh", "Quyết định"),
    ("cong-van", "Công văn"),
    ("ke-hoach", "Kế hoạch"),
    ("nghi-quyet", "Nghị quyết"),
    ("an-le", "Án lệ"),
    ("luat-", "Luật"),
)
_ADF_LOADER = re.compile(r"AdfLoopbackUtils|adf\.js", re.IGNORECASE)


class _AnchorParser(HTMLParser):
    """Thu mọi thẻ `<a>`: href và chữ bên trong (đã gộp khoảng trắng)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        self._href = dict(attrs).get("href") or ""
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._text).split())
            self.links.append((self._href, text))
            self._href = None
            self._text = []


def _anchors(html: str) -> list[tuple[str, str]]:
    parser = _AnchorParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # noqa: BLE001 — HTML rác: giữ những gì đã đọc được
        pass
    return parser.links


def _path_parts(url: str) -> list[str]:
    return [p for p in urlparse(url).path.split("/") if p]


def doc_number(text: str) -> str:
    """Số hiệu văn bản trong một dòng chữ; không có thì trả ""."""
    for rx in (_NUMBER_WITH_YEAR, _NUMBER_PLAIN):
        found = rx.search(text or "")
        if found:
            return found.group(1)
    return ""


def number_from_url(url: str) -> str:
    """Số hiệu khi trang chỉ để số hiệu trong đường dẫn ("-so-59-2020-qh14")."""
    found = _NUMBER_IN_SLUG.search(urlparse(url).path)
    if not found:
        return ""
    return f"{found.group(1)}/{found.group(2)}/{found.group(3).upper()}"


def doc_kind(title: str, url: str = "") -> str:
    """Loại văn bản theo tiêu đề, sau đó theo đường dẫn."""
    head = (title or "").strip()
    for prefix, kind in _KINDS:
        if head.lower().startswith(prefix.lower()):
            return kind
    slug = urlparse(url).path.lower()
    for needle, kind in _KIND_SLUGS:
        if needle in slug:
            return kind
    return ""


def listed_date(text: str) -> date | None:
    """Ngày hiển thị cạnh tiêu đề, chỉ khi có đủ ngày/tháng/năm."""
    found = _DATE_SHOWN.search(text or "")
    if not found:
        return None
    day, month, year = (int(part) for part in found.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def labor_hint(item: dict[str, Any]) -> bool:
    """Tin có khả năng liên quan lao động? (từ khoá trên tiêu đề + loại + đường dẫn)."""
    hay = " ".join(
        str(item.get(key) or "") for key in ("title", "kind", "category")
    ).lower()
    return any(keyword in hay for keyword in LABOR_KEYWORDS)


# Tiêu đề thật của văn bản luôn nêu loại văn bản; link phụ ("Liên quan hiệu lực", "Tải về"…)
# trỏ cùng URL nhưng không có, nên bị bỏ.
_TITLE_KIND = re.compile(
    r"(nghị định|thông tư|quyết định|nghị quyết|công văn|kế hoạch|văn bản hợp nhất|bộ luật|luật|"
    r"pháp lệnh|chỉ thị|án lệ|dự thảo|thông báo|hướng dẫn)",
    re.IGNORECASE,
)


def _keep(found: dict[str, dict[str, Any]], url: str, item: dict[str, Any]) -> None:
    """Chỉ nhận tiêu đề có loại văn bản; cùng URL thì giữ tiêu đề dài nhất."""
    if not _TITLE_KIND.search(item["title"]):
        return
    old = found.get(url)
    if old is None or len(item["title"]) > len(old["title"]):
        found[url] = item


def make_item(source: str, url: str, title: str, category: str = "") -> dict[str, Any]:
    """Một dòng tin theo đúng khoá mà `store.add_item` nhận."""
    return {
        "source": source,
        "url": url,
        "title": title,
        "number": doc_number(title) or number_from_url(url),
        "kind": doc_kind(title, url),
        "category": category,
        "listed_date": listed_date(title),
    }


class ThuVienPhapLuat:
    """thuvienphapluat.vn — trang chủ liệt kê văn bản mới, loại nằm trong đường dẫn."""

    name = "thuvienphapluat"
    listing_urls = ("https://thuvienphapluat.vn/",)
    last_status = "ok"
    _SECTIONS = ("van-ban", "cong-van")

    def parse(self, html: str, base_url: str) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for href, title in _anchors(html):
            if not href or len(title) < 12:
                continue
            url = urljoin(base_url, href.strip())
            parts = _path_parts(url)
            if len(parts) < 2 or parts[0] not in self._SECTIONS:
                continue
            _keep(found, url, make_item(self.name, url, title, parts[1]))
        return list(found.values())


class LuatVietnam:
    """luatvietnam.vn/van-ban-moi.html — link văn bản kết thúc bằng `-d<n>.html`."""

    name = "luatvietnam"
    listing_urls = ("https://luatvietnam.vn/van-ban-moi.html",)
    last_status = "ok"
    _DOC_LINK = re.compile(r"-d\d+\.html$")

    def parse(self, html: str, base_url: str) -> list[dict[str, Any]]:
        found: dict[str, dict[str, Any]] = {}
        for href, title in _anchors(html):
            if not href or len(title) < 12 or not self._DOC_LINK.search(href.strip()):
                continue
            url = urljoin(base_url, href.strip())
            parts = _path_parts(url)
            category = parts[0] if len(parts) > 1 else ""
            _keep(found, url, make_item(self.name, url, title, category))
        return list(found.values())


class AnLe:
    """anle.toaan.gov.vn — Oracle ADF; HTTP thường chỉ trả loader nên không có item."""

    name = "anle"
    listing_urls = ("https://anle.toaan.gov.vn/",)
    last_status = "needs_browser"

    def parse(self, html: str, base_url: str) -> list[dict[str, Any]]:
        if _ADF_LOADER.search(html or ""):
            self.last_status = "needs_browser"  # cần trình duyệt headless, chưa được duyệt cài
        return []
