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
- anle.toaan.gov.vn: ứng dụng Oracle ADF (JavaScript) — HTTP thường chỉ trả về loader, nên
  adapter này chạy qua `fetch.Renderer` (Chromium headless, LI2). Trang chủ đã render có ba
  khối "ÁN LỆ MỚI" (`chitietanle?dDocName=TAND…`), "DỰ THẢO ÁN LỆ MỚI"
  (`chitietanleduthao?dDocName=…`) và "NGUỒN ÁN LỆ" (`chitietnguonanle?dDocName=…`). Toàn
  văn là tệp công khai `ShowProperty?nodeId=/UCMServer/<dDocName>`.
- vanban.chinhphu.vn: robots `Allow: /`; trang chủ có bảng văn bản mới (số hiệu, ngày,
  trích yếu) kèm PDF công khai trên datafiles.chinhphu.vn. Phân trang không đổi nội dung nên
  chỉ đọc trang 1; nhịp quét 6 giờ đủ bắt văn bản mới khi còn ở trang 1.
- congbao.chinhphu.vn: trang chủ liệt kê văn bản mới nhưng chỉ tra theo số hiệu chứ không
  quét danh sách — phần đó nằm ở `intel/official.py` (LI3).
- vbpl.vn: robots cấm `/api/` và `/Pages/`, ô tìm kiếm chuyển thẳng về trang chủ — không
  triển khai (LI3 chỉ giữ chỗ đánh dấu `robots_disallow`).
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
    # "án lệ" đã bỏ: mọi án lệ (dân sự, đất đai, hình sự…) đều chứa chữ này nên bị coi là
    # lao động và tốn lượt Dahl. Án lệ chỉ được xét khi tiêu đề có từ lao động ở trên.
    "hợp đồng lao động",
    "sa thải",
    "kỷ luật lao động",
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


def plain_text(html: str) -> str:
    """Chữ của trang (bỏ thẻ), khoảng trắng đã gộp — đủ để đọc câu trạng thái."""
    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    parser = _Text()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # noqa: BLE001 — HTML rác: giữ những gì đã đọc được
        pass
    return " ".join("".join(parser.parts).split())


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


class _RowParser(HTMLParser):
    """Thu từng hàng `<tr>`: chữ của mỗi ô (đã gộp khoảng trắng) và link trong ô."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[dict[str, Any]]] = []
        self._row: list[dict[str, Any]] | None = None
        self._cell: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = {"text": [], "links": []}
        elif tag == "a" and self._cell is not None:
            href = dict(attrs).get("href")
            if href:
                self._cell["links"].append(href)

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append({
                "text": " ".join("".join(self._cell["text"]).split()),
                "links": self._cell["links"],
            })
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None


def _rows(html: str) -> list[list[dict[str, Any]]]:
    parser = _RowParser()
    try:
        parser.feed(html or "")
        parser.close()
    except Exception:  # noqa: BLE001 — HTML rác: giữ những gì đã đọc được
        pass
    return parser.rows


ANLE_PDF_URL = "https://anle.toaan.gov.vn/webcenter/ShowProperty?nodeId=/UCMServer/{key}"
_ANLE_KEY = re.compile(r"[?&]dDocName=([A-Za-z0-9_.:-]+)")
_AL_NUMBER = re.compile(r"(\d{1,4}/\d{4}/AL)\b", re.IGNORECASE)
_DRAFT_NUMBER = re.compile(r"Số\s*(\d{1,4}/\d{4})", re.IGNORECASE)


def doc_key(url: str) -> str:
    """Khoá tài liệu của anle (`dDocName`) trong URL; không có thì ""."""
    found = _ANLE_KEY.search(url or "")
    return found.group(1) if found else ""


def anle_pdf_url(key: str) -> str:
    """Tệp toàn văn công khai của một án lệ theo `dDocName`."""
    return ANLE_PDF_URL.format(key=key)


def _anle_kind(url: str) -> str:
    path = urlparse(url).path.lower()
    if "chitietanleduthao" in path:
        return "Dự thảo án lệ"
    if "chitietnguonanle" in path:
        return "Nguồn án lệ"
    if "chitietanle" in path:
        return "Án lệ"
    return ""


def kind_number(kind: str, text: str) -> str:
    """Số hiệu theo loại: "84/2026/AL", "DỰ THẢO 42/2026", "143/2025/DS-PT"."""
    if kind == "Dự thảo án lệ":
        found = _DRAFT_NUMBER.search(text or "")
        return f"DỰ THẢO {found.group(1)}" if found else doc_number(text)
    if kind == "Án lệ":
        found = _AL_NUMBER.search(text or "")
        return found.group(1).upper() if found else doc_number(text)
    return doc_number(text)


def document_summary(text: str, number: str) -> str:
    """Trích yếu của một dòng bảng: bỏ số hiệu, ngày ban hành, nhãn "Tài liệu đính kèm"."""
    rest = (text or "").split(number, 1)[-1]
    rest = _DATE_SHOWN.sub(" ", rest, count=1)
    rest = re.sub(r"(Tài liệu đính kèm\s*)+", " ", rest)
    return " ".join(rest.split())


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
    """anle.toaan.gov.vn — đọc trang chủ đã render (Playwright) thành án lệ/dự thảo/nguồn."""

    name = "anle"
    listing_urls = ("https://anle.toaan.gov.vn/webcenter/portal/anle/home",)
    needs_render = True
    last_status = "ok"

    def parse(self, html: str, base_url: str) -> list[dict[str, Any]]:
        if _ADF_LOADER.search(html or ""):
            self.last_status = "needs_browser"  # chỉ có loader: chưa render được
            return []
        found: dict[str, dict[str, Any]] = {}
        for href, text in _anchors(html):
            key = doc_key(href)
            kind = _anle_kind(href)
            if not key or not kind or not text:
                continue
            url = urljoin(base_url, href.strip())
            item = make_item(self.name, url, text)
            item.update(kind=kind, number=kind_number(kind, text), doc_key=key)
            found[url] = item
        self.last_status = "ok"
        return list(found.values())


class VanBanChinhPhu:
    """vanban.chinhphu.vn — bảng văn bản mới ở trang chủ, mỗi dòng một PDF công khai."""

    name = "vanban.chinhphu"
    listing_urls = ("https://vanban.chinhphu.vn/",)
    needs_render = True
    last_status = "ok"
    _PDF_HOST = "datafiles.chinhphu.vn"

    def parse(self, html: str, base_url: str) -> list[dict[str, Any]]:
        """Mỗi số hiệu một item; nhiều tệp đính kèm của cùng văn bản giữ tệp đầu tiên."""
        found: dict[str, dict[str, Any]] = {}
        for row in _rows(html):
            text = row[0]["text"] if row else ""
            number = doc_number(text)
            if not number or number in found:
                continue
            pdf = next(
                (
                    urljoin(base_url, href.strip())
                    for cell in row
                    for href in cell["links"]
                    if self._PDF_HOST in href and href.lower().endswith(".pdf")
                ),
                "",
            )
            if not pdf:
                continue
            summary = document_summary(text, number)
            item = make_item(self.name, pdf, f"{number} {summary}".strip())
            item.update(
                number=number,
                kind=doc_kind(summary, pdf),
                listed_date=listed_date(text),
                pdf_url=pdf,
            )
            found[number] = item
        return list(found.values())


class CongBao:
    """congbao.chinhphu.vn — trang chủ liệt kê văn bản mới nhưng LI3 tra theo số hiệu
    (`intel/official.py`) chứ không quét danh sách; trả rỗng."""

    name = "congbao"
    listing_urls: tuple[str, ...] = ()
    last_status = "not_implemented"

    def parse(self, html: str, base_url: str) -> list[dict[str, Any]]:
        return []


class Vbpl:
    """vbpl.vn — robots cấm `/api/` và `/Pages/`, tìm kiếm chuyển về trang chủ: không quét."""

    name = "vbpl"
    listing_urls: tuple[str, ...] = ()
    last_status = "robots_disallow"

    def parse(self, html: str, base_url: str) -> list[dict[str, Any]]:
        return []
