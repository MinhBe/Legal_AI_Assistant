"""Khung thời gian của câu trả lời (T2, design §5.2).

Code quyết định ngày sự kiện và luật áp dụng; LLM không bao giờ tự chọn phiên bản
luật. Hàm ở đây thuần Python + đọc DB, không gọi LLM.

    extract_event_date("bị sa thải ngày 20/12/2020", today) -> (date(2020,12,20), "ngày")
    resolve(db, event, advice) -> dict cho prompt và hộp "Khung thời gian" ở UI
"""

from __future__ import annotations

import calendar
import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    DocumentRelation,
    LegalDocument,
    LegalLink,
    LegalNode,
    ProvisionVersion,
    TransitionRule,
)

# Ngày dạng chữ đứng trước để không bắt nhầm số hiệu văn bản; mọi mẫu đều bắt buộc
# đủ năm 4 chữ số nên "45/2019/QH14" hay "Điều 25" không khớp.
_DAY_WORDS = re.compile(
    r"ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE
)
_DAY_NUM = re.compile(r"(?<!\d)(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})(?![\d/])")
_MONTH_WORDS = re.compile(r"tháng\s+(\d{1,2})\s+năm\s+(\d{4})", re.IGNORECASE)
_MONTH_NUM = re.compile(r"tháng\s+(\d{1,2})\s*/\s*(\d{4})", re.IGNORECASE)
_YEAR = re.compile(r"năm\s+(\d{4})", re.IGNORECASE)
# tên văn bản đứng ngay trước "năm YYYY" (không qua dấu câu): năm ban hành, không phải ngày sự kiện
_DOC_BEFORE = re.compile(
    r"(bộ\s*luật|luật|nghị\s*định|thông\s*tư|quyết\s*định|blld|bllđ|nđ)[^.,;:!?\n]{0,30}$",
    re.IGNORECASE,
)

GRAN_DAY, GRAN_MONTH, GRAN_YEAR = "ngày", "tháng", "năm"

_NO_EVENT = "không nêu — dùng ngày tư vấn"
_EVENT = "câu hỏi"
_GUARD_MSG = (
    "Có văn bản mới sau ngày sự kiện, chưa có quy tắc chuyển tiếp: cần luật sư xác nhận"
)
_PENALTY_FLAG = "Lĩnh vực xử phạt: cần luật sư xác nhận"
_PENALTY_HINTS = ("xử phạt", "phạt vi phạm")


def _month_end(year: int, month: int) -> date | None:
    if not 1 <= month <= 12:
        return None
    return date(year, month, calendar.monthrange(year, month)[1])


def _day(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None          # 31/02, tháng 13… không phải ngày thật


def extract_event_date(text: str, advice_date: date) -> tuple[date | None, str]:
    """Ngày sự kiện trong câu hỏi và độ chi tiết của nó.

    Nhiều ngày: lấy ngày gần nhất không sau ngày tư vấn (hành vi tranh chấp thường
    được kể sau cùng); toàn bộ ở tương lai thì lấy ngày sớm nhất.
    """
    rest = text or ""
    found: list[tuple[date | None, str]] = []

    def take(pattern: re.Pattern[str], build) -> None:
        nonlocal rest
        for m in pattern.finditer(rest):
            if pattern is _YEAR and _DOC_BEFORE.search(rest[max(0, m.start() - 40):m.start()]):
                continue  # "Bộ luật Lao động năm 2019" là tên văn bản, không phải ngày sự kiện
            found.append((build(m), _gran_of(pattern)))
        rest = pattern.sub(" ", rest)   # đã dùng thì che đi, mẫu sau không bắt lại

    take(_DAY_WORDS, lambda m: _day(int(m[3]), int(m[2]), int(m[1])))
    take(_DAY_NUM, lambda m: _day(int(m[3]), int(m[2]), int(m[1])))
    take(_MONTH_WORDS, lambda m: _month_end(int(m[2]), int(m[1])))
    take(_MONTH_NUM, lambda m: _month_end(int(m[2]), int(m[1])))
    take(_YEAR, lambda m: _day(int(m[1]), 12, 31))

    found = [(d, g) for d, g in found if d is not None]
    if not found:
        return None, ""
    past = [(d, g) for d, g in found if d <= advice_date]
    return max(past) if past else min(found)


def _gran_of(pattern: re.Pattern[str]) -> str:
    if pattern in (_DAY_WORDS, _DAY_NUM):
        return GRAN_DAY
    if pattern in (_MONTH_WORDS, _MONTH_NUM):
        return GRAN_MONTH
    return GRAN_YEAR


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def _label(doc: dict) -> str:
    return doc.get("title") or doc.get("number") or doc["doc_id"]


def blank(event_date: date | None, advice_date: date) -> dict:
    """Khung thời gian rỗng — dùng khi không dựng được từ DB."""
    event = event_date or advice_date
    return {
        "event_date": _iso(event_date),
        "event_date_source": _EVENT if event_date else _NO_EVENT,
        "advice_date": _iso(advice_date),
        "as_of": _iso(event),
        "applicable": [],
        "changes_after": [],
        "upcoming": [],
        "transition_rules": [],
        "flags": [],
    }


def _doc_row(r) -> dict:
    return {"doc_id": r.doc_id, "title": r.title, "number": r.number}


def _docs_at(db: Session, as_of: date) -> list[dict]:
    rows = db.execute(
        select(LegalDocument.doc_id, LegalDocument.title, LegalDocument.number)
        .where(
            LegalDocument.doc_type.is_distinct_from("upload"),
            (LegalDocument.effective_date.is_(None)) | (LegalDocument.effective_date <= as_of),
            (LegalDocument.expired_date.is_(None)) | (LegalDocument.expired_date > as_of),
        )
        .order_by(LegalDocument.effective_date, LegalDocument.doc_id)
    )
    return [_doc_row(r) for r in rows]


def _changes(db: Session, as_of: date, advice_date: date) -> list[dict]:
    rows = db.execute(
        select(
            LegalDocument.doc_id, LegalDocument.title, LegalDocument.number,
            LegalDocument.effective_date,
        )
        .where(
            LegalDocument.doc_type.is_distinct_from("upload"),
            LegalDocument.effective_date > as_of,
            LegalDocument.effective_date <= advice_date,
        )
        .order_by(LegalDocument.effective_date, LegalDocument.doc_id)
    ).all()
    if not rows:
        return []
    keys = [r.doc_id for r in rows]
    replaces: dict[str, list[str]] = {k: [] for k in keys}
    # legal_link giữ cả node_id (T1 sinh từ node_supersession) nên quy về doc_id
    for from_key, to_doc in db.execute(
        select(LegalLink.from_key, LegalNode.doc_id)
        .join(LegalNode, LegalNode.node_id == LegalLink.to_key)
        .where(LegalLink.link_type == "replaces", LegalLink.from_key.in_(keys))
    ):
        if to_doc not in replaces[from_key]:
            replaces[from_key].append(to_doc)
    for from_doc, to_doc in db.execute(
        select(DocumentRelation.from_doc, DocumentRelation.to_doc).where(
            DocumentRelation.rel == "REPLACES", DocumentRelation.from_doc.in_(keys)
        )
    ):
        if to_doc not in replaces[from_doc]:
            replaces[from_doc].append(to_doc)
    return [
        {
            **_doc_row(r),
            "effective_date": _iso(r.effective_date),
            "replaces": replaces.get(r.doc_id, []),
        }
        for r in rows
    ]


_PENDING = ("not_yet_in_force", "pending_amendment")


def _upcoming(db: Session, advice_date: date) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    rows = db.execute(
        select(
            LegalDocument.doc_id, LegalDocument.title, LegalDocument.number,
            LegalDocument.effective_date,
        )
        .where(
            LegalDocument.doc_type.is_distinct_from("upload"),
            LegalDocument.effective_date > advice_date,
        )
        .order_by(LegalDocument.effective_date, LegalDocument.doc_id)
    ).all()
    for r in rows:
        seen.add(r.doc_id)
        out.append({**_doc_row(r), "effective_date": _iso(r.effective_date),
                    "status": "chưa có hiệu lực"})

    pending_ids = list(db.execute(
        select(LegalDocument.doc_id)
        .join(ProvisionVersion, ProvisionVersion.doc_id == LegalDocument.doc_id)
        .where(ProvisionVersion.status.in_(_PENDING))
        .distinct()
    ).scalars())
    for doc_id in pending_ids:
        if doc_id in seen:
            continue
        r = db.execute(
            select(LegalDocument.doc_id, LegalDocument.title, LegalDocument.number,
                   LegalDocument.effective_date)
            .where(LegalDocument.doc_id == doc_id)
        ).one()
        out.append({**_doc_row(r), "effective_date": _iso(r.effective_date),
                    "status": "chờ sửa đổi"})
    return out


def _rules(db: Session, doc_keys: list[str]) -> list[dict]:
    if not doc_keys:
        return []
    rows = db.execute(
        select(
            TransitionRule.doc_key, TransitionRule.condition, TransitionRule.outcome,
            TransitionRule.provision_ref, TransitionRule.note,
        )
        .where(TransitionRule.doc_key.in_(doc_keys))
        .order_by(TransitionRule.doc_key)
    )
    return [
        {
            "doc_key": r.doc_key,
            "condition": r.condition,
            "outcome": r.outcome,
            "provision_ref": r.provision_ref,
            "note": r.note,
        }
        for r in rows
    ]


def resolve(
    db: Session,
    event_date: date | None,
    advice_date: date,
    topic_hint: str = "",
) -> dict:
    """Luật áp dụng tại ngày sự kiện (hoặc ngày tư vấn) + thay đổi sau đó."""
    as_of = event_date or advice_date
    applicable = _docs_at(db, as_of)
    changes_after = _changes(db, as_of, advice_date)
    transition_rules = _rules(db, [c["doc_id"] for c in changes_after])
    upcoming = _upcoming(db, advice_date)

    flags: list[str] = []
    if changes_after and not transition_rules:
        flags.append(_GUARD_MSG)
    hint = (topic_hint or "").casefold()
    if any(h in hint for h in _PENALTY_HINTS):
        flags.append(_PENALTY_FLAG)

    return {
        "event_date": _iso(event_date),
        "event_date_source": _EVENT if event_date else _NO_EVENT,
        "advice_date": _iso(advice_date),
        "as_of": _iso(as_of),
        "applicable": applicable,
        "changes_after": changes_after,
        "upcoming": upcoming,
        "transition_rules": transition_rules,
        "flags": flags,
    }


def _vn(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d/%m/%Y") if iso else "—"


def summary_lines(tf: dict) -> list[str]:
    """2–4 dòng ngắn đưa vào prompt để LLM biết mốc thời gian đã chốt."""
    if not tf:
        return []
    applied = ", ".join(_label(d) for d in tf.get("applicable") or []) or "chưa xác định"
    if tf.get("event_date"):
        lines = [f"Ngày sự kiện: {_vn(tf['event_date'])}. Luật áp dụng: {applied}."]
    else:
        lines = [f"Không nêu ngày sự kiện; áp dụng luật tại ngày tư vấn "
                 f"{_vn(tf.get('as_of'))}: {applied}."]
    if tf.get("changes_after"):
        parts = [f"{_label(c)} có hiệu lực {_vn(c.get('effective_date'))}"
                 for c in tf["changes_after"]]
        lines.append("Sau ngày sự kiện: " + "; ".join(parts)
                     + " (chỉ để cảnh báo, không làm căn cứ).")
    if tf.get("upcoming"):
        lines.append("Sắp thay đổi, không dùng làm căn cứ: "
                     + ", ".join(_label(d) for d in tf["upcoming"]) + ".")
    if tf.get("transition_rules"):
        lines.append("Đã xét quy tắc chuyển tiếp: " + "; ".join(
            f"{r['doc_key']} — {r['condition']}" for r in tf["transition_rules"][:2]) + ".")
    if tf.get("flags"):
        lines.append("Cần lưu ý: " + "; ".join(tf["flags"]) + ".")
    return lines[:4]
