"""Toàn văn công khai của tin ưu tiên (LI2).

Chỉ tải tệp công khai từ nguồn chính thức: PDF án lệ (`ShowProperty?…/UCMServer/<dDocName>`),
PDF đính kèm trên datafiles.chinhphu.vn, và tệp Công báo theo số hiệu (`intel/official.py`,
LI3). Tệp đi thẳng vào luồng tải lên bình thường (`upload.service.save_upload`) nên vẫn nằm
chờ luật sư duyệt; không áp quy tắc mức A vì đây là văn bản công khai.

Thứ tự nguồn: tệp án lệ → PDF vanban.chinhphu của cùng lượt quét → Công báo (tối đa 5 lượt
tra mỗi lần quét). Không nguồn nào có thì ghi `not_found` thay vì ném lỗi.

401/403/429 → `blocked` (không thử lại trong cùng lượt quét, giao diện báo "cần lấy tay").
Quá `intel_fulltext_max_mb` → `failed`.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from loguru import logger
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import IntelDoc, IntelItem, UploadedFile
from app.intel import official, sources, store, watchlist
from app.intel.fetch import BLOCKED_STATUS, TOO_LARGE, Fetcher
from app.upload import service as upload_service

PDF_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
MAX_TEXT_CHARS = 6000
MAX_CONGBAO_LOOKUPS = 5
_SUFFIX = {"application/pdf": ".pdf", "application/msword": ".doc"}
STATUSES = ("fetched", "ingested", "failed", "blocked", "not_found")
NOT_FOUND = "không tìm thấy ở nguồn công khai"
# shortcut: ngày hiệu lực lấy từ Công báo chỉ sống trong tiến trình (mất khi khởi động lại),
# thêm cột vào intel_doc khi cần giữ qua những lượt quét khác nhau.
_EFFECTIVE_DATES: dict[str, str] = {}


def size_limit(settings: Settings) -> int:
    return max(int(settings.intel_fulltext_max_mb), 1) * 1024 * 1024


def candidates(item: IntelItem, pdf_urls: dict[str, str]) -> list[str]:
    """Tệp công khai đã biết của tin: PDF án lệ, PDF của đúng số hiệu trên vanban.chinhphu."""
    if item.source == "anle":
        key = sources.doc_key(item.url)
        return [sources.anle_pdf_url(key)] if key else []
    if item.source == "vanban.chinhphu":
        return [item.url]
    url = pdf_urls.get((item.number or "").lower(), "")
    return [url] if url else []


def _filename(item: IntelItem, url: str, mime: str) -> str:
    name = Path(urlparse(url).path).name
    if name.lower().endswith((".pdf", ".doc", ".docx")):
        return name
    stem = (item.number or item.id).replace("/", "-")
    return f"{stem}{_SUFFIX.get(mime, '.docx')}"


def fetch_one(
    db: Session, settings: Settings, fetcher: Fetcher, item: IntelItem, url: str
) -> IntelDoc:
    """Tải một tệp; nạp vào kho nếu hợp lệ. Trả dòng `intel_doc` đã ghi."""
    code, data, mime = fetcher.get_bytes(url, max_bytes=size_limit(settings))
    if code in BLOCKED_STATUS:
        return store.save_doc(db, item.id, source_url=url, status="blocked", error=f"HTTP {code}")
    if code == TOO_LARGE:
        return store.save_doc(
            db,
            item.id,
            source_url=url,
            status="failed",
            error=f"tệp lớn hơn {settings.intel_fulltext_max_mb} MB",
        )
    if code != 200 or not data:
        return store.save_doc(
            db, item.id, source_url=url, status="failed", error=f"HTTP {code}" if code else "lỗi tải"
        )
    if mime not in PDF_TYPES:
        return store.save_doc(
            db, item.id, source_url=url, status="failed", error=f"content-type {mime or 'trống'}"
        )
    store.save_doc(db, item.id, source_url=url, data=data, status="fetched")
    try:
        upload = upload_service.save_upload(
            db, data, _filename(item, url, mime), title=item.title
        )
    except Exception as exc:  # noqa: BLE001 — tệp hỏng: giữ dòng lỗi, lượt quét vẫn chạy
        logger.warning("Không nạp được toàn văn của tin {}: {}", item.id, exc)
        return store.save_doc(
            db,
            item.id,
            source_url=url,
            data=data,
            status="failed",
            error=f"{exc.__class__.__name__}: {exc}",
        )
    if upload.status == "failed":  # save_upload không ném lỗi mà ghi row failed (vd. tệp không đọc được)
        return store.save_doc(
            db,
            item.id,
            source_url=url,
            data=data,
            status="failed",
            error=f"nạp lỗi: {upload.error or 'không rõ'}",
            upload_id=upload.upload_id,
        )
    return store.save_doc(
        db,
        item.id,
        source_url=url,
        data=data,
        status="ingested",
        upload_id=upload.upload_id,
    )


def from_congbao(
    db: Session, settings: Settings, fetcher: Fetcher, item: IntelItem, render
) -> IntelDoc | None:
    """Tải tệp Công báo của đúng số hiệu; ghi nhớ ngày hiệu lực cho bước phân tích."""
    try:
        found = official.congbao_lookup(item.number, render)
    except Exception as exc:  # noqa: BLE001 — site đổi bố cục: tin khác vẫn lấy được
        logger.warning("Không tra được Công báo cho tin {}: {}", item.id, exc)
        return None
    if not found:
        return None
    if found["effective_date"]:
        _EFFECTIVE_DATES[item.id] = found["effective_date"].isoformat()
    last = None
    for file in found["files"]:  # DOCX trước, rồi PDF (official.parse_files đã xếp)
        last = fetch_one(db, settings, fetcher, item, file["url"])
        if last.status == "ingested":
            return last
    return last


def scan(
    db: Session,
    settings: Settings,
    fetcher: Fetcher,
    pdf_urls: dict[str, str],
    *,
    render=None,
) -> dict[str, int]:
    """Lấy toàn văn cho tin mới priority ≥ 1 chưa có `intel_doc`. Trả số đếm theo trạng thái."""
    counts = dict.fromkeys(STATUSES, 0)
    numbers = watchlist.corpus_numbers(db)
    lookups = 0
    for item in store.pending(db):
        if store.get_doc(db, item.id) is not None or watchlist.priority(item, numbers) < 1:
            continue
        doc = None
        for url in candidates(item, pdf_urls):
            doc = fetch_one(db, settings, fetcher, item, url)
            if doc.status == "ingested":
                break
        if doc is None or doc.status != "ingested":
            if render is not None and lookups < MAX_CONGBAO_LOOKUPS and item.number:
                lookups += 1
                doc = from_congbao(db, settings, fetcher, item, render) or doc
            if doc is None:
                doc = store.save_doc(
                    db, item.id, source_url="", status="not_found", error=NOT_FOUND
                )
        counts[doc.status] += 1
    return counts


def text_for(db: Session, item_id: str, limit: int = MAX_TEXT_CHARS) -> str:
    """Toàn văn đã trích của một tin (đoạn đầu), "" nếu chưa có.

    Kèm dòng hiệu lực khi tệp đến từ Công báo: ngày do code đọc, nằm ngay trong ngữ cảnh
    phân tích (analyze đọc qua hàm này).
    """
    try:
        doc = store.get_doc(db, item_id)
        if doc is None or doc.status != "ingested" or not doc.upload_id:
            return ""
        row = db.get(UploadedFile, doc.upload_id)
        if row is None:
            return ""
        day = _EFFECTIVE_DATES.get(item_id)
        header = f"Hiệu lực: {day} (nguồn Công báo)\n" if day else ""
        return (header + upload_service.full_text(db, row))[:limit]
    except Exception as exc:  # noqa: BLE001 — thiếu toàn văn thì vẫn phân tích được
        logger.warning("Không đọc được toàn văn của tin {}: {}", item_id, exc)
        return ""
