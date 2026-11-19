"""Toàn văn chính thức theo số hiệu trên Công báo điện tử (LI3).

Sự thật đo ngày 2026-11-16: trang chủ `congbao.chinhphu.vn` liệt kê văn bản mới, mỗi văn bản
có trang `/van-ban/<slug>-<id>.htm` chứa link tải trên `g7.cdnchinhphu.vn/api/download/stream`
mà chữ của link là tên tệp (`2026_576_399/2026/NĐ-CP.docx`, `…pdf`) và dòng
"Hiệu lực: dd/mm/yyyy". Trang có ô tìm kiếm `input[name=keyword]`; form gửi GET nên tra theo
số hiệu = mở `tim-kiem-van-ban.htm?keyword=` (nếu site đổi cách gửi, chỉ hỏng bước tìm kiếm này).

Chỉ tải tệp công khai của Công báo. Nguồn tin (thuvienphapluat, luatvietnam, vanban.chinhphu)
không được dùng để lấy toàn văn: không cookie, không đăng nhập, không vượt rào chặn bot.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urljoin, urlparse

from app.intel import sources

CONGBAO_HOME = "https://congbao.chinhphu.vn/"
# đo 18/11/2026: ô tìm kiếm chuyển tới trang này; "/?keyword=" chỉ trả lại trang chủ
SEARCH_URL = CONGBAO_HOME + "tim-kiem-van-ban.htm?keyword={keyword}"
DOC_PATH = "/van-ban/"  # trang chi tiết một văn bản
DOWNLOAD_HOST = "cdnchinhphu.vn"  # link tải công khai (g7.cdnchinhphu.vn)
FILE_EXTS = ("docx", "pdf", "doc")  # thứ tự ưu tiên: DOCX đọc được bảng, rồi PDF
_EFFECTIVE = r"Hiệu\s*lực\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})"

Render = Callable[[str], str]


def _key(text: str) -> str:
    """Chữ để so khớp: gộp khoảng trắng, chữ thường."""
    return " ".join((text or "").split()).lower()


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-zđ]", "", (text or "").lower())


def effective_date(html: str) -> date | None:
    """Ngày "Hiệu lực: dd/mm/yyyy" trên trang chi tiết; không có thì None."""
    found = re.search(_EFFECTIVE, sources.plain_text(html), re.IGNORECASE)
    if not found:
        return None
    day, month, year = (int(part) for part in found.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def parse_list(html: str, base_url: str = CONGBAO_HOME) -> list[dict[str, str]]:
    """Các văn bản trên trang chủ / trang kết quả tìm kiếm: `{title, url}`."""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, text in sources._anchors(html):
        url = urljoin(base_url, href.strip())
        if DOC_PATH not in urlparse(url).path or not text or url in seen:
            continue
        seen.add(url)
        rows.append({"title": text, "url": url})
    return rows


def find_page(number: str, html: str, base_url: str = CONGBAO_HOME) -> dict[str, str] | None:
    """Trang văn bản đầu tiên có tiêu đề chứa số hiệu."""
    needle = _key(number)
    if not needle:
        return None
    rows = parse_list(html, base_url)
    # văn bản sửa đổi cũng nhắc số hiệu trong tiêu đề ("…sửa đổi Luật số 31/2024/QH15"): ưu tiên
    # tiêu đề mà số hiệu nằm ngay đầu ("Luật số 41/2024/QH15 …")
    for row in rows:
        if needle in _key(row["title"][:40]):
            return row
    for row in rows:
        if needle in _key(row["title"]):
            return row
    return None


def parse_files(html: str, base_url: str, number: str = "") -> list[dict[str, str]]:
    """Tệp tải về của một văn bản, DOCX trước rồi PDF; chỉ link có tên chứa số hiệu."""
    # tên tệp viết số hiệu bằng "-" hoặc "_" ("…_41-2024-QH15.pdf"): so khớp chỉ trên chữ và số
    needle = _alnum(number)
    found: list[dict[str, str]] = []
    for href, text in sources._anchors(html):
        url = urljoin(base_url, href.strip())
        name = " ".join((text or "").split())
        ext = Path(name).suffix.lower().lstrip(".")
        if ext not in FILE_EXTS or DOWNLOAD_HOST not in urlparse(url).netloc:
            continue
        if needle and needle not in _alnum(name):
            continue
        found.append({"name": name, "url": url, "ext": ext})
    found.sort(key=lambda row: FILE_EXTS.index(row["ext"]))
    return found


def congbao_lookup(number: str, render: Render | None) -> dict[str, Any] | None:
    """Trang Công báo + tệp công khai của một số hiệu; None = không thấy.

    Đọc trang chủ trước (văn bản mới luôn ở đó); không có thì tra ô tìm kiếm với số hiệu.
    `render` là hàm tải trang đã chạy JavaScript (`fetch.Renderer.render`).
    """
    number = (number or "").strip()
    if not number or render is None:
        return None
    search = SEARCH_URL.format(keyword=quote(number))
    for list_url in (CONGBAO_HOME, search):  # trang chủ trước; không có tệp thì tra ô tìm kiếm
        page = find_page(number, render(list_url), list_url)
        if page is None:
            continue
        html = render(page["url"])
        files = parse_files(html, page["url"], number)
        if files:
            return {"page_url": page["url"], "files": files, "effective_date": effective_date(html)}
    return None
