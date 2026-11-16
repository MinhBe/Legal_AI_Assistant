"""Hạn duyệt (SLA) và lịch luật sư trực (R7, design §9.4, §15.5).

    due_at(case)      # + 1 ngày làm việc, hoặc + 4 giờ khi gần mốc thời hiệu
    overdue(case)     # ca chờ duyệt đã quá hạn
    get_duty(db)      # {"on_duty", "lawyer", "backup", "updated_at"}
    set_duty(db, False)  # tắt trực: mọi loại ca về mức 0

Chưa cần giờ làm việc 08:00–17:00: chỉ cộng 24 giờ rồi đẩy qua Thứ Bảy/Chủ Nhật.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import DutyStatus

DEFAULT_LAWYER = "Luật sư chính"
DEFAULT_BACKUP = "Luật sư dự phòng"


def _codes(case: Any) -> set[str]:
    try:
        rows = json.loads(case.reasons or "[]")
    except (TypeError, ValueError):
        return set()
    return {row.get("code") for row in rows if isinstance(row, dict)}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def due_at(case: Any) -> datetime:
    created = _aware(case.created_at or datetime.now(UTC))
    if "near_limitation" in _codes(case):
        return created + timedelta(hours=4)
    due = created + timedelta(hours=24)
    while due.weekday() >= 5:  # Thứ Bảy, Chủ Nhật
        due += timedelta(days=1)
    return due


def overdue(case: Any, now: datetime | None = None) -> bool:
    if case.status != "pending":
        return False
    return due_at(case) < _aware(now or datetime.now(UTC))


def duty_row(row: DutyStatus) -> dict[str, Any]:
    return {
        "on_duty": row.on_duty,
        "lawyer": row.lawyer,
        "backup": row.backup,
        "updated_at": row.updated_at,
    }


def is_on_duty(db: Session) -> bool:
    row = db.get(DutyStatus, 1)
    return True if row is None else bool(row.on_duty)


def get_duty(db: Session) -> dict[str, Any]:
    row = db.get(DutyStatus, 1)
    if row is None:
        return {"on_duty": True, "lawyer": DEFAULT_LAWYER, "backup": DEFAULT_BACKUP,
                "updated_at": None}
    return duty_row(row)


def set_duty(db: Session, on_duty: bool, lawyer: str | None = None,
             backup: str | None = None) -> dict[str, Any]:
    row = db.get(DutyStatus, 1)
    if row is None:
        row = DutyStatus(id=1, on_duty=True, lawyer=DEFAULT_LAWYER, backup=DEFAULT_BACKUP)
        db.add(row)
    row.on_duty = bool(on_duty)
    if lawyer and lawyer.strip():
        row.lawyer = lawyer.strip()
    if backup and backup.strip():
        row.backup = backup.strip()
    row.updated_at = datetime.now(UTC)
    if not row.on_duty:
        from app.review.autonomy import demote_all

        demote_all(db, "Không có luật sư trực")
    db.commit()
    return duty_row(row)
