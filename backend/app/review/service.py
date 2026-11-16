"""Bàn duyệt luật sư (R2, design §9.2–9.3): gói ca, bốn hành động, thống kê.

    pkg = package(db, case_id)          # gói ca gửi luật sư
    act(db, case_id, "light_edit", text="...")   # một trong bốn hành động
    import_json_escalations(db, path)   # nhập một lần escalations.json cũ

Không đổi schema: lý do/lời nhắn cho người hỏi nằm ở `reply`, lý do sửa nhiều nằm ở
đầu khối `diff`, nhãn lỗi ở `error_labels`.
"""

from __future__ import annotations

import difflib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import AnswerRecord, LegalNode, ReviewCase

ERROR_LABELS = {
    "sai_trich_dan": "Sai trích dẫn",
    "sai_phien_ban": "Sai phiên bản luật",
    "thieu_can_cu": "Thiếu căn cứ",
    "sai_tinh_toan": "Sai tính toán",
    "sai_su_kien": "Hiểu sai tình tiết",
    "van_phong": "Văn phong",
    "khac": "Khác",
}

ACTION_STATUS = {
    "approve": "approved",
    "light_edit": "light_edit",
    "heavy_edit": "heavy_edit",
    "reject": "rejected",
}

# trạng thái ca -> trạng thái cũ mà thẻ phê duyệt trong chat đang đọc
_ESC_STATUS = {"approved": "approved", "light_edit": "approved",
               "heavy_edit": "approved", "rejected": "denied"}

IMPORTED_STATUS = {"approved": "approved", "denied": "rejected"}


class BadInput(ValueError):
    """Đầu vào sai (HTTP 422)."""


def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return default


def case_row(case: ReviewCase) -> dict:
    return {
        "id": case.id,
        "created_at": case.created_at,
        "question": case.question,
        "risk_score": case.risk_score,
        "reasons": _json(case.reasons, []),
        "status": case.status,
        "source": case.source,
        "answer_id": case.answer_id,
        "thread_id": case.thread_id,
        "case_type": case.case_type,
        "reviewer_text": case.reviewer_text,
        "diff": case.diff,
        "error_labels": _json(case.error_labels, []),
        "reply": case.reply,
        "reviewed_at": case.reviewed_at,
    }


def _record(db: Session, case: ReviewCase) -> AnswerRecord | None:
    return db.get(AnswerRecord, case.answer_id) if case.answer_id else None


def _provisions(db: Session, cited: Any) -> list[dict]:
    """Căn cứ đã trích + toàn văn node trong kho luật."""
    out: list[dict] = []
    for item in cited if isinstance(cited, list) else []:
        node_id = item.get("node_id") if isinstance(item, dict) else item
        if not node_id:
            continue
        node = db.get(LegalNode, node_id)
        out.append({
            "node_id": node_id,
            "doc_id": (item.get("doc_id") if isinstance(item, dict) else None)
            or (node.doc_id if node else None),
            "heading": node.heading if node else None,
            "text": (node.text if node else "") or "",
        })
    return out


def package(db: Session, case_id: str) -> dict:
    """Gói ca gửi luật sư; ca do người dùng gửi (chưa có hồ sơ) chỉ có câu hỏi."""
    case = db.get(ReviewCase, case_id)
    if case is None:
        raise LookupError(f"Không tìm thấy ca {case_id}")
    out = case_row(case)
    out.update({"draft": None, "timeframe": None, "verifier": None, "provisions": [],
                "prompt_version": None, "model": None, "provider": None,
                "as_of": None, "category": None})
    rec = _record(db, case)
    if rec is None:
        return out
    out.update({
        "draft": rec.answer,
        "timeframe": _json(rec.timeframe, None),
        "verifier": _json(rec.verifier, None),
        "provisions": _provisions(db, _json(rec.provisions, [])),
        "prompt_version": rec.prompt_version,
        "model": rec.model,
        "provider": rec.provider,
        "as_of": rec.as_of.isoformat() if rec.as_of else None,
        "category": rec.category,
    })
    return out


def _diff(draft: str, text: str, reason: str = "") -> str:
    lines = list(difflib.unified_diff(
        (draft or "").splitlines(), text.splitlines(),
        fromfile="bản nháp", tofile="bản sửa", lineterm="",
    ))
    # shortcut: chưa có cột `reason` cho ca sửa nhiều — ghép vào đầu diff;
    # nâng cấp: thêm cột reason khi được phép đổi schema.
    return ("Lý do: " + reason + "\n" if reason else "") + "\n".join(lines)


def act(db: Session, case_id: str, action: str, text: str = "",
        labels: list[str] | None = None, reason: str = "") -> dict:
    """Ghi một trong bốn hành động của luật sư; trả về ca sau khi cập nhật."""
    text = (text or "").strip()
    reason = (reason or "").strip()
    labels = list(labels or [])
    if action not in ACTION_STATUS:
        raise BadInput(f"Hành động không hợp lệ: {action}")
    bad = [name for name in labels if name not in ERROR_LABELS]
    if bad:
        raise BadInput("Nhãn lỗi không hợp lệ: " + ", ".join(bad))
    case = db.get(ReviewCase, case_id)
    if case is None:
        raise LookupError(f"Không tìm thấy ca {case_id}")
    if case.status != "pending":
        raise ValueError(f"Ca đã được xử lý ({case.status})")
    rec = _record(db, case)
    draft = rec.answer if rec else None

    if action in ("light_edit", "heavy_edit"):
        if not text:
            raise BadInput("Sửa thì phải có bản sửa")
        if action == "heavy_edit" and not labels:
            raise BadInput("Sửa nhiều thì phải gắn ít nhất một nhãn lỗi")
    elif action == "reject" and not reason:
        raise BadInput("Từ chối thì phải nêu lý do")
    elif action == "approve" and draft is None and not text:
        raise BadInput("Chưa có phương án trả lời để duyệt")

    case.status = ACTION_STATUS[action]
    case.reviewed_at = datetime.now(UTC)
    case.error_labels = json.dumps(labels, ensure_ascii=False) if labels else None
    if action == "approve":
        case.reviewer_text = draft if draft is not None else text
        case.diff = None
    elif action in ("light_edit", "heavy_edit"):
        case.reviewer_text = text
        case.diff = _diff(draft or "", text, reason)
    else:
        case.reviewer_text = None
        case.diff = None
    # `reply` là bản gửi cho người hỏi: câu trả lời đã duyệt/sửa, hoặc lý do từ chối.
    case.reply = reason if action == "reject" else case.reviewer_text
    db.commit()
    return case_row(case)


def stats(db: Session) -> dict:
    """Đếm theo trạng thái và nhãn lỗi — đầu vào cho tỷ lệ duyệt thẳng (§9.3)."""
    by_status = {name: 0 for name in ("pending", *ACTION_STATUS.values())}
    for status, n in db.execute(
        select(ReviewCase.status, func.count()).group_by(ReviewCase.status)
    ):
        by_status[status] = n
    by_label: dict[str, int] = {}
    for (raw,) in db.execute(select(ReviewCase.error_labels).where(
            ReviewCase.error_labels.is_not(None))):
        for name in _json(raw, []):
            by_label[name] = by_label.get(name, 0) + 1
    total = sum(by_status.values())
    decided = total - by_status["pending"]
    return {
        "total": total,
        "by_status": by_status,
        "by_label": by_label,
        "approved_rate": round(by_status["approved"] / decided, 4) if decided else None,
    }


def _day(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def import_json_escalations(db: Session, path: str | Path) -> int:
    """Nhập escalations.json (bản ghi cũ bằng tệp) vào `review_case`; bỏ qua id đã có."""
    path = Path(path)
    if not path.exists():
        return 0
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return 0
    existing = set(db.scalars(select(ReviewCase.id)).all())
    added = 0
    for row in rows if isinstance(rows, list) else []:
        raw_id = str(row.get("id") or "")
        if not raw_id:
            continue
        # shortcut: cột id là String(16), id cũ dài 32 ký tự — cắt bớt;
        # nâng cấp: khi escalation cũ có bảng riêng thì giữ nguyên id.
        case_id = raw_id[:16]
        if case_id in existing:
            continue
        status = IMPORTED_STATUS.get(row.get("status") or "pending", "pending")
        db.add(ReviewCase(
            id=case_id,
            question=row.get("question") or "",
            thread_id=row.get("thread_id"),
            risk_score="",
            reasons="[]",
            status=status,
            source="user",
            reply=row.get("reply") or None,
            created_at=_day(row.get("created_at")),
            reviewed_at=_day(row.get("resolved_at")),
        ))
        existing.add(case_id)
        added += 1
    if added:
        db.commit()
    return added


def esc_row(case: ReviewCase) -> dict:
    """Hình dạng cũ của escalation mà thẻ phê duyệt trong chat đang đọc."""
    return {
        "id": case.id,
        "question": case.question,
        "thread_id": case.thread_id,
        "status": "pending" if case.status == "pending" else _ESC_STATUS.get(case.status, "pending"),
        "created_at": case.created_at,
        "reply": case.reply,
        "resolved_at": case.reviewed_at,
    }
