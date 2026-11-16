"""Đọc/ghi `intel_item`, `intel_doc` và `intel_run` (LI1, LI2).

URL là khoá tự nhiên của tin: `add_item` bỏ qua URL đã có, nên quét lại nhiều lần không sinh
trùng và tin đã lưu không bao giờ bị tải lại hay phân tích lại. `intel_doc` giữ toàn văn
công khai đã tải cho một tin (mỗi tin tối đa một tệp) và `upload_id` của luồng tải lên.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import IntelDoc, IntelImpact, IntelItem, IntelRun, LegalDocument
from app.intel import sources, watchlist

STATUSES = ("new", "analysed", "skipped", "approved", "ignored", "blocked")


def new_id() -> str:
    return uuid.uuid4().hex[:16]


def in_corpus(db: Session, number: str | None) -> bool:
    """Số hiệu đã có trong kho luật chưa?"""
    if not number:
        return False
    return bool(
        db.scalar(select(func.count()).select_from(LegalDocument).where(LegalDocument.number == number))
    )


def known_urls(db: Session) -> set[str]:
    return set(db.scalars(select(IntelItem.url)).all())


def add_item(db: Session, data: dict[str, Any]) -> IntelItem | None:
    """Thêm một tin; URL đã có (hoặc rỗng) thì trả None."""
    url = (data.get("url") or "").strip()
    if not url or db.scalar(select(IntelItem.id).where(IntelItem.url == url)):
        return None
    item = IntelItem(
        id=new_id(),
        source=(data.get("source") or "")[:32],
        url=url,
        title=data.get("title") or "",
        number=(data.get("number") or "")[:64],
        kind=(data.get("kind") or "")[:32],
        category=(data.get("category") or "")[:64],
        listed_date=data.get("listed_date"),
        labor_hint=bool(data.get("labor_hint")),
        in_corpus=in_corpus(db, data.get("number")),
        status="new",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def get_item(db: Session, item_id: str) -> IntelItem | None:
    return db.get(IntelItem, item_id)


def pending(db: Session) -> list[IntelItem]:
    """Tin chờ phân tích (status `new`)."""
    return list(db.scalars(select(IntelItem).where(IntelItem.status == "new")).all())


# ---- toàn văn công khai (LI2) ----
def get_doc(db: Session, item_id: str) -> IntelDoc | None:
    return db.get(IntelDoc, item_id)


def save_doc(
    db: Session,
    item_id: str,
    *,
    source_url: str,
    data: bytes = b"",
    status: str = "fetched",
    error: str | None = None,
    upload_id: str | None = None,
) -> IntelDoc:
    """Ghi (hoặc ghi lại) toàn văn của một tin; mỗi tin một dòng."""
    doc = db.get(IntelDoc, item_id) or IntelDoc(item_id=item_id)
    doc.source_url = source_url
    doc.sha256 = hashlib.sha256(data).hexdigest() if data else (doc.sha256 or "")
    doc.bytes = len(data) if data else (doc.bytes or 0)
    doc.status = status
    doc.error = (error or "")[:500] or None
    doc.upload_id = upload_id
    doc.fetched_at = datetime.now().astimezone()
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def doc_dict(doc: IntelDoc) -> dict[str, Any]:
    return {
        "status": doc.status,
        "source_url": doc.source_url,
        "upload_id": doc.upload_id,
        "upload_url": "/upload",
        "bytes": doc.bytes,
        "fetched_at": doc.fetched_at.isoformat() if doc.fetched_at else None,
        "error": doc.error,
    }


def save_analysis(db: Session, item: IntelItem, analysis: dict[str, Any]) -> None:
    item.analysis = json.dumps(analysis, ensure_ascii=False)
    item.status = "analysed"
    item.error = None
    db.commit()


def set_error(db: Session, item: IntelItem, error: str) -> None:
    """Lỗi phân tích: giữ status `new` để lượt sau thử lại."""
    item.error = error[:500]
    item.status = "new"
    db.commit()


def set_status(db: Session, item: IntelItem, status: str, reviewer: str | None = None) -> IntelItem:
    item.status = status
    if reviewer is not None:
        item.reviewed_by = reviewer[:32]
        item.reviewed_at = datetime.now().astimezone()
    db.commit()
    db.refresh(item)
    return item


# ---- ảnh hưởng của tin (LI2b) ----
IMPACT_FIELDS = ("articles", "calculators", "golden", "answers", "summary")


def get_impact(db: Session, item_id: str) -> IntelImpact | None:
    return db.get(IntelImpact, item_id)


def save_impact(db: Session, item_id: str, data: dict[str, Any]) -> IntelImpact:
    """Ghi (hoặc ghi lại) ảnh hưởng của một tin.

    Chỉ các trường có trong `data` được ghi, nên phân tích lại không xoá `case_id`.
    """
    row = db.get(IntelImpact, item_id) or IntelImpact(item_id=item_id)
    for field in IMPACT_FIELDS:
        if field in data:
            value = data[field]
            setattr(row, field, value if field == "summary" else json.dumps(value, ensure_ascii=False))
    row.computed_at = datetime.now().astimezone()
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def impact_dict(row: IntelImpact) -> dict[str, Any]:
    out: dict[str, Any] = {
        "item_id": row.item_id,
        "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        "case_id": row.case_id,
    }
    for field in IMPACT_FIELDS:
        raw = row.summary if field == "summary" else json.loads(getattr(row, field) or "[]")
        out[field] = raw or ("" if field == "summary" else [])
    return out


def items(
    db: Session, *, status: str | None = None, labor: bool | None = None, limit: int = 200
) -> list[IntelItem]:
    """Tin mới nhất trước; `status`/`labor` để trống = không lọc."""
    query = select(IntelItem).order_by(IntelItem.first_seen.desc(), IntelItem.id.desc())
    if status:
        query = query.where(IntelItem.status == status)
    if labor is not None:
        query = query.where(IntelItem.labor_hint.is_(labor))
    return list(db.scalars(query.limit(limit)).all())


# ---- lượt quét ----
def start_run(db: Session, trigger: str) -> IntelRun:
    run = IntelRun(trigger=trigger)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def finish_run(
    db: Session, run: IntelRun, per_source: dict[str, Any], error: str | None = None
) -> IntelRun:
    run.per_source = json.dumps(per_source, ensure_ascii=False)
    run.error = error[:1000] if error else None
    run.finished_at = datetime.now().astimezone()
    db.commit()
    db.refresh(run)
    return run


def runs(db: Session, limit: int = 10) -> list[IntelRun]:
    return list(db.scalars(select(IntelRun).order_by(IntelRun.id.desc()).limit(limit)).all())


# ---- để API trả JSON ----
def item_dict(
    db: Session, item: IntelItem, numbers: set[str] | None = None
) -> dict[str, Any]:
    """JSON của một tin; `priority`/`fulltext` tính tại chỗ (không có cột riêng)."""
    doc = get_doc(db, item.id)
    return {
        "id": item.id,
        "source": item.source,
        "url": item.url,
        "title": item.title,
        "number": item.number,
        "kind": item.kind,
        "category": item.category,
        "doc_key": sources.doc_key(item.url),
        "listed_date": item.listed_date.isoformat() if item.listed_date else None,
        "first_seen": item.first_seen.isoformat() if item.first_seen else None,
        "labor_hint": item.labor_hint,
        "in_corpus": item.in_corpus,
        "priority": watchlist.priority(
            item, numbers if numbers is not None else watchlist.corpus_numbers(db)
        ),
        "fulltext": doc_dict(doc) if doc else None,
        "status": item.status,
        "analysis": json.loads(item.analysis) if item.analysis else None,
        "error": item.error,
        "reviewed_by": item.reviewed_by,
        "reviewed_at": item.reviewed_at.isoformat() if item.reviewed_at else None,
    }


def run_dict(run: IntelRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "trigger": run.trigger,
        "per_source": json.loads(run.per_source) if run.per_source else {},
        "error": run.error,
    }
