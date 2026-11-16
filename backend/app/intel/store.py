"""Đọc/ghi `intel_item` và `intel_run` (LI1).

URL là khoá tự nhiên: `add_item` bỏ qua URL đã có, nên quét lại nhiều lần không sinh trùng
và tin đã lưu không bao giờ bị tải lại hay phân tích lại.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import IntelItem, IntelRun, LegalDocument

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
def item_dict(item: IntelItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "source": item.source,
        "url": item.url,
        "title": item.title,
        "number": item.number,
        "kind": item.kind,
        "category": item.category,
        "listed_date": item.listed_date.isoformat() if item.listed_date else None,
        "first_seen": item.first_seen.isoformat() if item.first_seen else None,
        "labor_hint": item.labor_hint,
        "in_corpus": item.in_corpus,
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
