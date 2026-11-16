"""Mức tự chủ theo loại ca (R4, design §9.4, §15.1).

    case_type("Công ty sa thải tôi có đúng luật?")   # "cham_dut"
    get_level(db, "cham_dut")                        # thiếu dòng = mức 0
    set_level(db, "cham_dut", 1, "đủ 60 ca sạch")
    on_review(db, case)                              # lỗi nghiêm trọng -> tụt 0

Thang 0–3: 0 luật sư duyệt từng ca, 1 gửi khách kèm nhãn "chưa xác nhận",
2 kiểm mẫu, 3 tự xử lý. Chỉ luật sư đổi mức; code chỉ hạ khi có lỗi nghiêm trọng
hoặc không có người trực.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.guard import normalize
from app.db.models import AutonomyLevel, ReviewCase

CASE_TYPES = ("cham_dut", "tien_luong", "nghi_ngoi", "ky_luat", "hop_dong", "khac")

# Khớp trên chữ đã bỏ dấu (guard.normalize), nên viết không dấu.
_KEYWORDS = {
    "cham_dut": ("sa thai", "duoi viec", "cham dut", "thoi viec"),
    "tien_luong": ("luong", "thuong", "lam them"),
    "nghi_ngoi": ("nghi phep", "nghi le", "thai san"),
    "ky_luat": ("ky luat",),
    "hop_dong": ("hop dong", "thu viec"),
}

# design §15.1: lỗi nghiêm trọng = viện dẫn sai điều, sai phiên bản, sai tính toán.
SEVERE_LABELS = ("sai_trich_dan", "sai_phien_ban", "sai_tinh_toan")

NO_LAWYER_REASON = "Không có luật sư trực"


def case_type(question: str) -> str:
    text = normalize(question or "")
    for name in CASE_TYPES:
        if name != "khac" and any(word in text for word in _KEYWORDS[name]):
            return name
    return "khac"


def _row(row: AutonomyLevel) -> dict[str, Any]:
    return {
        "case_type": row.case_type,
        "level": row.level,
        "reason": row.reason,
        "updated_at": row.updated_at,
    }


def get_level(db: Session, ct: str) -> int:
    row = db.get(AutonomyLevel, ct)
    return row.level if row is not None else 0


def set_level(db: Session, ct: str, level: int, reason: str = "") -> dict[str, Any]:
    if level not in (0, 1, 2, 3):
        raise ValueError("Mức tự chủ chỉ nhận 0, 1, 2 hoặc 3")
    row = db.get(AutonomyLevel, ct)
    if row is None:
        row = AutonomyLevel(case_type=ct, level=level)
        db.add(row)
    row.level = level
    row.reason = (reason or "").strip() or None
    row.updated_at = datetime.now(UTC)
    db.commit()
    return _row(row)


def all_levels(db: Session) -> list[dict[str, Any]]:
    """Mọi loại ca (kèm loại lạ đã có trong bảng) với mức hiện tại."""
    rows = {row.case_type: row for row in db.scalars(select(AutonomyLevel))}
    order = [*CASE_TYPES, *sorted(set(rows) - set(CASE_TYPES))]
    return [
        _row(rows[ct]) if ct in rows else
        {"case_type": ct, "level": 0, "reason": None, "updated_at": None}
        for ct in order
    ]


def on_review(db: Session, case: ReviewCase) -> dict[str, Any] | None:
    """Ca vừa xử lý: sửa nhiều/từ chối kèm lỗi nghiêm trọng -> loại ca tụt về 0."""
    if case.status not in ("heavy_edit", "rejected"):
        return None
    try:
        labels = json.loads(case.error_labels or "[]")
    except ValueError:
        labels = []
    severe = next((name for name in labels if name in SEVERE_LABELS), None)
    if severe is None:
        return None
    ct = case.case_type or case_type(case.question)
    return set_level(
        db, ct, 0, f"Tụt về 0 do lỗi nghiêm trọng ({severe}) ở ca {case.id}"
    )


def demote_all(db: Session, reason: str = NO_LAWYER_REASON) -> int:
    """Không có người trực: mọi loại ca về 0, dừng gửi khách (design §15.5)."""
    rows = list(db.scalars(select(AutonomyLevel)))
    now = datetime.now(UTC)
    for row in rows:
        row.level = 0
        row.reason = reason
        row.updated_at = now
    db.flush()
    return len(rows)
