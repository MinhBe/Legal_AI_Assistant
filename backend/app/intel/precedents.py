"""Danh mục án lệ công khai của anle.toaan.gov.vn (LI3).

Trang danh mục là ứng dụng Oracle ADF (JavaScript), phân trang bằng GET:
`…/portal/anle/anle?selectedPage=<n>&docType=AnLe`, 20 án lệ mỗi trang. Sự thật đo ngày
2026-11-16: `wait_until="domcontentloaded"` + chờ 8 giây thì đọc được, `networkidle` không
bao giờ tới. Mỗi án lệ có link số hiệu và link tiêu đề cùng `dDocName`; toàn văn là tệp công
khai `ShowProperty?nodeId=/UCMServer/<dDocName>`.

Trạng thái: chỉ mở trang chi tiết của án lệ MỚI một lần; câu nào vừa nhắc "án lệ" vừa nhắc
"bãi bỏ"/"hủy bỏ"/"không còn áp dụng"/"hết hiệu lực" thì đánh dấu `bi_huy_bo` và giữ nguyên
câu đó làm ghi chú, còn lại `dang_ap_dung`. Không suy đoán trạng thái từ tiêu đề.

Tệp toàn văn tải bằng `Fetcher` (robots, giãn cách, trần kích thước) rồi vào luồng tải lên
bình thường (`upload.service.save_upload`) ở trạng thái chờ luật sư duyệt; án lệ lao động trước.
"""

from __future__ import annotations

import re
from datetime import datetime
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import PrecedentCatalog
from app.intel import sources
from app.intel.fetch import Fetcher
from app.upload import service as upload_service

LIST_URL = "https://anle.toaan.gov.vn/webcenter/portal/anle/anle?selectedPage={page}&docType=AnLe"
DETAIL_URL = "https://anle.toaan.gov.vn/webcenter/portal/anle/chitietanle?dDocName={key}"
STATUSES = ("dang_ap_dung", "bi_huy_bo", "chua_ro")
CANCEL_PHRASES = ("bãi bỏ", "hủy bỏ", "huỷ bỏ", "không còn áp dụng", "hết hiệu lực")
MAX_FILES_PER_RUN = 10
SETTLE_MS = 8000  # ADF cần thời gian dựng bảng; networkidle không bao giờ tới

Render = Callable[[str], str]
_NUMBER = re.compile(r"\d{1,4}/\d{4}/AL", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.!?])\s+|\n+")
_NOISE = ("Thuộc tính", "Văn bản liên quan")


def list_render(renderer: Any) -> Render:
    """`render` cho trang danh mục: `domcontentloaded` + chờ `SETTLE_MS`.

    `fetch.Renderer` dùng `load` + `networkidle` (hợp cho trang thường) và không nhận tham số
    chiến lược tải, nên phần này mở trang trên cùng Chromium của lượt quét.
    """
    fetcher = renderer.fetcher

    def render(url: str) -> str:
        if not fetcher.allowed(url):
            logger.info("robots.txt không cho phép {} — không render", url)
            return ""
        fetcher._throttle(urlparse(url).netloc)
        try:
            page = renderer._open().new_page(user_agent=fetcher.user_agent)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                page.wait_for_timeout(SETTLE_MS)
                html = page.content()
            finally:
                page.close()
        except Exception as exc:  # noqa: BLE001 — trình duyệt hỏng: lượt quét vẫn chạy
            logger.warning("Không render được {}: {}", url, exc.__class__.__name__)
            return ""
        fetcher._cache(url, html)
        return html

    return render


def parse_list(html: str) -> list[dict[str, Any]]:
    """Án lệ trên một trang danh mục: `{doc_key, number, title, url, file_url}`."""
    found: dict[str, dict[str, Any]] = {}
    for href, text in sources._anchors(html):
        key = sources.doc_key(href)
        if not key:
            continue
        row = found.setdefault(key, {"doc_key": key, "number": "", "title": ""})
        label = " ".join((text or "").split())
        if _NUMBER.fullmatch(label):
            row["number"] = label.upper()
        elif len(label) >= 12 and label not in _NOISE and not row["title"]:
            row["title"] = label
    rows = [row for row in found.values() if row["number"]]
    for row in rows:
        row["url"] = DETAIL_URL.format(key=row["doc_key"])
        row["file_url"] = sources.anle_pdf_url(row["doc_key"])
    return rows


_NON_TEXT = re.compile(r"(?is)<(script|style|noscript)\b[^>]*>.*?</\1>")
_BLOCK = re.compile(r"(?i)</?(p|div|li|ul|ol|br|tr|td|th|h[1-6]|section|article|table)\b[^>]*>")
_CANCEL_RE = re.compile(
    r"(bãi bỏ|hủy bỏ|huỷ bỏ)\s+(các\s+)?án lệ"
    r"|án lệ[^.;]{0,40}?(đã\s+)?bị\s+(bãi bỏ|hủy bỏ|huỷ bỏ)"
    r"|án lệ[^.;]{0,60}?(không còn (được\s+)?áp dụng|hết hiệu lực áp dụng)"
)


def status_of(html: str, number: str = "") -> tuple[str, str]:
    """`(trạng thái, ghi chú)` đọc từ câu trên trang chi tiết.

    Chỉ tính câu nhắc ĐÚNG số hiệu án lệ này cùng cụm "bãi bỏ/hủy bỏ…": trang anle có script và
    khung tin chung (xuất hiện ở mọi trang) chứa các từ đó, trước đây làm mọi án lệ bị coi là
    đã huỷ bỏ."""
    # Tự tách dòng ở thẻ khối (plain_text gộp mọi khoảng trắng nên cả trang thành một "câu"),
    # rồi tách câu; bỏ đoạn dài > 400 ký tự (menu/khối dính liền, không phải một câu thật).
    import html as html_lib

    raw = _BLOCK.sub("\n", _NON_TEXT.sub(" ", html))
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", raw))
    num = (number or "").lower()
    for line in text.splitlines():
        for sentence in _SENTENCE.split(line):
            sentence = " ".join(sentence.split())
            if not sentence or len(sentence) > 400:
                continue
            low = sentence.lower()
            # Hành động phải nhắm vào chính án lệ ("bãi bỏ án lệ…", "án lệ … bị bãi bỏ"), vì tiêu đề
            # án lệ hay tự chứa "hủy bỏ"/"hết hiệu lực" của đối tượng khác (giấy chứng nhận, hợp đồng…).
            if _CANCEL_RE.search(low) and (not num or num in low):
                return "bi_huy_bo", sentence[:500]
    return "dang_ap_dung", ""


def upsert(
    db: Session,
    row: dict[str, Any],
    *,
    status: str | None = None,
    note: str = "",
) -> PrecedentCatalog:
    """Ghi một án lệ; đã có thì cập nhật số hiệu/tiêu đề/link và `last_checked`."""
    entry = db.get(PrecedentCatalog, row["doc_key"])
    is_new = entry is None
    if entry is None:
        entry = PrecedentCatalog(doc_key=row["doc_key"], status="chua_ro")
    entry.number = (row.get("number") or "")[:32]
    entry.title = row.get("title") or ""
    entry.url = row.get("url") or ""
    entry.file_url = row.get("file_url") or ""
    entry.last_checked = datetime.now().astimezone()
    if is_new and status:
        entry.status = status
        entry.status_note = note
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def crawl(render: Render, fetcher: Fetcher, db: Session, max_pages: int = 10) -> dict[str, int]:
    """Quét danh mục (trang 1..n) rồi tải toàn văn còn thiếu. Trả số đếm."""
    counts = dict.fromkeys(("pages", "found", "new", "cancelled", "uploaded"), 0)
    known = set(db.scalars(select(PrecedentCatalog.doc_key)).all())
    seen: set[str] = set()
    for page in range(1, max(1, max_pages) + 1):
        rows = parse_list(render(LIST_URL.format(page=page)) or "")
        if not any(row["doc_key"] not in seen for row in rows):
            break  # trang không thêm gì mới = đã hết danh mục
        counts["pages"] += 1
        counts["found"] += len(rows)
        for row in rows:
            if row["doc_key"] in seen:
                continue
            seen.add(row["doc_key"])
            if row["doc_key"] in known:
                upsert(db, row)
                continue
            status, note = status_of(render(row["url"]) or "", row.get("number", ""))
            upsert(db, row, status=status, note=note)
            counts["new"] += 1
            if status == "bi_huy_bo":
                counts["cancelled"] += 1
    counts["uploaded"] = fetch_texts(fetcher, db)
    return counts


def fetch_texts(fetcher: Fetcher, db: Session) -> int:
    """Tải toàn văn cho án lệ chưa có tệp: án lệ lao động trước, tối đa 10 tệp mỗi lượt."""
    limit = max(int(get_settings().intel_fulltext_max_mb), 1) * 1024 * 1024
    rows = list(
        db.scalars(select(PrecedentCatalog).where(PrecedentCatalog.upload_id.is_(None))).all()
    )
    rows.sort(key=lambda row: 0 if sources.labor_hint({"title": row.title}) else 1)
    done = 0
    for row in rows[:MAX_FILES_PER_RUN]:
        code, data, _mime = fetcher.get_bytes(row.file_url, max_bytes=limit)
        if code != 200 or not data:
            continue
        title = f"Án lệ {row.number}: {row.title}".strip()
        name = f"an-le-{(row.number or row.doc_key).replace('/', '-')}.pdf"
        try:
            upload = upload_service.save_upload(db, data, name, title=title)
        except Exception as exc:  # noqa: BLE001 — tệp hỏng: lượt sau thử lại
            logger.warning("Không nạp được toàn văn án lệ {}: {}", row.number, exc)
            continue
        if upload.status == "failed":
            continue
        row.upload_id = upload.upload_id
        db.commit()
        done += 1
    return done


def rows(db: Session, limit: int = 500) -> list[PrecedentCatalog]:
    """Án lệ mới thấy trước."""
    query = select(PrecedentCatalog).order_by(
        PrecedentCatalog.first_seen.desc(), PrecedentCatalog.doc_key.desc()
    )
    return list(db.scalars(query.limit(limit)).all())


def catalog_dict(row: PrecedentCatalog) -> dict[str, Any]:
    return {
        "doc_key": row.doc_key,
        "number": row.number,
        "title": row.title,
        "url": row.url,
        "file_url": row.file_url,
        "status": row.status,
        "status_note": row.status_note,
        "first_seen": row.first_seen.isoformat() if row.first_seen else None,
        "last_checked": row.last_checked.isoformat() if row.last_checked else None,
        "upload_id": row.upload_id,
        "upload_url": "/upload",
    }
