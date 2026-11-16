"""Cờ "cần xác minh" lan truyền + độ tươi của kho văn bản (T3, design §5.3).

Văn bản hướng dẫn/dựa trên một văn bản gốc đã bị thay thì chính nó cũng cần
được xem lại. Hàm ở đây chỉ đọc DB, không đổi trạng thái nào và không gọi LLM.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import LegalDocument, LegalLink, LegalNode

FRESH_DAYS = 30
FRESH_DAYS_SANCTION = 14

_BASE_OUT = ("guides", "based_on")
_SANCTION_HINTS = ("xử phạt", "phạt vi phạm")


def _key_to_doc(db: Session, keys: set[str]) -> dict[str, str]:
    """Khoá liên kết có thể là doc_id hoặc node_id — quy hết về doc_id."""
    out: dict[str, str] = {}
    if not keys:
        return out
    for doc_id in db.scalars(select(LegalDocument.doc_id).where(LegalDocument.doc_id.in_(keys))):
        out[doc_id] = doc_id
    rest = keys - out.keys()
    if rest:
        for node_id, doc_id in db.execute(
            select(LegalNode.node_id, LegalNode.doc_id).where(LegalNode.node_id.in_(rest))
        ):
            out[node_id] = doc_id
    return out


def _in_force(doc: LegalDocument, day: date) -> bool:
    return (
        (doc.effective_date is None or doc.effective_date <= day)
        and (doc.expired_date is None or doc.expired_date > day)
    )


def needs_verification(
    db: Session, as_of: date, doc_ids: list[str] | None = None
) -> list[dict]:
    """Văn bản còn hiệu lực nhưng dựa trên một văn bản gốc đã bị thay tại `as_of`."""
    rows = db.execute(
        select(
            LegalLink.link_type,
            LegalLink.from_key,
            LegalLink.to_key,
            LegalLink.valid_from,
        )
    ).all()
    if not rows:
        return []
    keys = {k for r in rows for k in (r.from_key, r.to_key)}
    key_to_doc = _key_to_doc(db, keys)

    # ngày văn bản gốc bị thay theo cạnh "replaces" đã có hiệu lực
    replaced_since: dict[str, date] = {}
    for r in rows:
        if r.link_type != "replaces" or r.valid_from is None or r.valid_from > as_of:
            continue
        base = key_to_doc.get(r.to_key)
        if base and (base not in replaced_since or r.valid_from < replaced_since[base]):
            replaced_since[base] = r.valid_from

    wanted = set(key_to_doc.values())
    docs = {
        d.doc_id: d
        for d in db.scalars(select(LegalDocument).where(LegalDocument.doc_id.in_(wanted)))
    }

    allowed = set(doc_ids) if doc_ids is not None else None
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for r in rows:
        if r.link_type not in _BASE_OUT:
            continue
        src = key_to_doc.get(r.from_key)
        base = key_to_doc.get(r.to_key)
        if not src or not base or src == base:
            continue
        if allowed is not None and src not in allowed:
            continue
        if (src, base) in seen:
            continue
        src_doc, base_doc = docs.get(src), docs.get(base)
        if not src_doc or not base_doc or not _in_force(src_doc, as_of):
            continue
        since = None
        if base_doc.expired_date and base_doc.expired_date <= as_of:
            since = base_doc.expired_date
        elif base in replaced_since:
            since = replaced_since[base]
        if since is None:
            continue
        seen.add((src, base))
        base_title = base_doc.title or base_doc.number or base_doc.doc_id
        out.append(
            {
                "doc_id": src,
                "title": src_doc.title,
                "base_doc_id": base,
                "base_title": base_title,
                "since": since.isoformat(),
                "reason": (
                    f"Văn bản gốc {base_title} đã bị thay từ {since:%d/%m/%Y}: "
                    "cần xác minh văn bản này còn áp dụng không"
                ),
            }
        )
    out.sort(key=lambda i: (i["doc_id"], i["base_doc_id"]))
    return out


def corpus_freshness(db: Session, today: date, topic_hint: str = "") -> dict:
    """Kho văn bản có quá cũ so với hạn cập nhật của chủ đề hay không."""
    last = db.scalar(
        select(func.max(LegalDocument.created_at)).where(
            LegalDocument.doc_type.is_distinct_from("upload")
        )
    )
    hint = (topic_hint or "").casefold()
    threshold = (
        FRESH_DAYS_SANCTION if any(h in hint for h in _SANCTION_HINTS) else FRESH_DAYS
    )
    if last is None:
        return {"last_ingest": None, "threshold": threshold, "stale": False, "message": ""}
    last_ingest = last.date()
    days = (today - last_ingest).days
    stale = days > threshold
    message = ""
    if stale:
        message = (
            f"Kho văn bản nạp lần cuối {last_ingest:%d/%m/%Y} (quá {days} ngày): "
            "có thể chưa cập nhật văn bản mới"
        )
    return {
        "last_ingest": last_ingest.isoformat(),
        "threshold": threshold,
        "stale": stale,
        "message": message,
    }
