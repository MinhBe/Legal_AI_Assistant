"""Đăng ký theo dõi văn bản mới theo lĩnh vực (21/11/2026).

Người dùng chọn lĩnh vực (lao động, đất đai, thuế TNCN...) và từ khoá tuỳ chọn. Mỗi tin
quét được (IntelItem) được phân lĩnh vực bằng từ khoá (app.rag.domain.classify), không gọi
mô hình. Bảng tin của mỗi đăng ký = tin khớp lĩnh vực/từ khoá, mới nhất trước, kèm số tin
chưa đọc. Chưa gửi email/Zalo: chỉ báo trong ứng dụng.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db.base import Base
from app.db.models import IntelItem
from app.rag import domain

MAX_PER_OWNER = 10
MAX_KEYWORDS = 10


class IntelSubscription(Base):
    __tablename__ = "intel_subscription"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner: Mapped[str] = mapped_column(String(96), index=True)   # username hoặc mã trình duyệt
    name: Mapped[str] = mapped_column(String(120), default="")
    domains: Mapped[str] = mapped_column(Text, default="[]")     # JSON list mã lĩnh vực
    keywords: Mapped[str] = mapped_column(Text, default="[]")    # JSON list, khớp không phân biệt hoa thường
    seen_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def owner_of(user: dict) -> str:
    return f"u:{user['username']}" if user.get("username") else f"c:{user.get('client_id') or 'unknown'}"


def _clean(domains: list[str], keywords: list[str]) -> tuple[list[str], list[str]]:
    bad = [d for d in domains if d not in domain.LABELS]
    if bad:
        raise ValueError(f"Lĩnh vực không có: {', '.join(bad)}")
    kws = [k.strip().lower() for k in keywords if k and k.strip()][:MAX_KEYWORDS]
    if not domains and not kws:
        raise ValueError("Cần chọn ít nhất một lĩnh vực hoặc một từ khoá")
    return sorted(set(domains)), kws


def item_domains(item: IntelItem) -> list[str]:
    """Lĩnh vực của một tin. Nguồn đã gắn cờ lao động thì luôn có lao động."""
    found = domain.classify(f"{item.title} {item.category or ''}", fallback=False)
    if item.labor_hint and domain.LABOUR not in found:
        found.append(domain.LABOUR)
    return found


def matches(item: IntelItem, domains: list[str], keywords: list[str]) -> list[str]:
    """Lý do khớp (rỗng = không khớp)."""
    why = [f"lĩnh vực {domain.label(d)}" for d in item_domains(item) if d in domains]
    text = f"{item.title} {item.number or ''}".lower()
    why += [f'từ khoá "{k}"' for k in keywords if k in text]
    return why


def to_dict(sub: IntelSubscription, unread: int | None = None) -> dict[str, Any]:
    return {
        "id": sub.id,
        "name": sub.name,
        "domains": json.loads(sub.domains or "[]"),
        "domain_labels": [domain.label(d) for d in json.loads(sub.domains or "[]")],
        "keywords": json.loads(sub.keywords or "[]"),
        "seen_until": sub.seen_until.isoformat() if sub.seen_until else None,
        "created_at": sub.created_at.isoformat() if sub.created_at else None,
        **({"unread": unread} if unread is not None else {}),
    }


def create(db: Session, owner: str, name: str, domains: list[str], keywords: list[str]) -> IntelSubscription:
    n = db.scalar(select(func.count()).select_from(IntelSubscription).where(IntelSubscription.owner == owner)) or 0
    if n >= MAX_PER_OWNER:
        raise ValueError(f"Tối đa {MAX_PER_OWNER} đăng ký mỗi tài khoản")
    doms, kws = _clean(domains, keywords)
    sub = IntelSubscription(owner=owner, name=name.strip()[:120] or ", ".join(domain.label(d) for d in doms),
                            domains=json.dumps(doms), keywords=json.dumps(kws, ensure_ascii=False))
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def list_for(db: Session, owner: str) -> list[IntelSubscription]:
    return list(db.scalars(select(IntelSubscription).where(IntelSubscription.owner == owner)
                           .order_by(IntelSubscription.id)).all())


def get(db: Session, owner: str, sub_id: int) -> IntelSubscription | None:
    sub = db.get(IntelSubscription, sub_id)
    return sub if sub is not None and sub.owner == owner else None


def delete(db: Session, sub: IntelSubscription) -> None:
    db.delete(sub)
    db.commit()


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def feed(db: Session, sub: IntelSubscription, limit: int = 50, scan: int = 500) -> dict[str, Any]:
    """Tin khớp đăng ký, mới nhất trước; `unread` = khớp và thấy sau `seen_until`."""
    doms = json.loads(sub.domains or "[]")
    kws = json.loads(sub.keywords or "[]")
    rows = db.scalars(select(IntelItem).order_by(IntelItem.first_seen.desc(), IntelItem.id.desc())
                      .limit(scan)).all()
    seen = _aware(sub.seen_until)
    items, unread = [], 0
    for it in rows:
        why = matches(it, doms, kws)
        if not why:
            continue
        is_new = seen is None or (_aware(it.first_seen) or seen) > seen
        unread += is_new
        if len(items) < limit:
            items.append({
                "id": it.id, "title": it.title, "number": it.number, "kind": it.kind,
                "source": it.source, "url": it.url,
                "listed_date": it.listed_date.isoformat() if it.listed_date else None,
                "first_seen": it.first_seen.isoformat() if it.first_seen else None,
                "in_corpus": it.in_corpus, "status": it.status,
                "domains": [domain.label(d) for d in item_domains(it)],
                "why": why, "unread": is_new,
            })
    return {"subscription": to_dict(sub, unread), "items": items}


def mark_read(db: Session, sub: IntelSubscription) -> IntelSubscription:
    sub.seen_until = datetime.now(timezone.utc)
    db.commit()
    db.refresh(sub)
    return sub
