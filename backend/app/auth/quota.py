"""Hạn mức câu hỏi mỗi ngày theo vai trò (AUTH1), đếm trong bảng `usage_count`.

Khách vãng lai đếm theo mã trình duyệt (X-Client-Id, thiếu thì theo IP) nên đổi
trình duyệt là có lượt mới — chấp nhận được cho bản demo nội bộ.
"""

from __future__ import annotations

from datetime import date

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.auth import roles
from app.config import get_settings
from app.db.models import UsageCount

settings = get_settings()


def key_for(user: dict) -> str:
    username = user.get("username")
    return f"user:{username}" if username else f"anon:{user.get('client_id') or 'unknown'}"


def _used(db: Session, key: str, day: date) -> int:
    row = db.get(UsageCount, (key, day))
    return row.n if row else 0


def remaining(db: Session, user: dict) -> int | None:
    """Số câu còn lại hôm nay; None = không giới hạn (hoặc đang tắt kiểm tra quyền)."""
    daily = roles.conf(user["role"])["daily"]
    if daily is None or not settings.auth_required:
        return None
    return max(daily - _used(db, key_for(user), date.today()), 0)


def check_and_count(db: Session, user: dict) -> int | None:
    """Đếm một câu hỏi trước khi chạy chat; quá hạn mức -> HTTP 429."""
    daily = roles.conf(user["role"])["daily"]
    if daily is None or not settings.auth_required:  # AUTH_REQUIRED=false: bỏ cả hạn mức
        return None
    key, day = key_for(user), date.today()
    row = db.get(UsageCount, (key, day))
    used = row.n if row else 0
    if used >= daily:
        raise HTTPException(
            status_code=429,
            detail=f"Đã hết {daily} câu hỏi hôm nay cho tài khoản {user['role']}",
        )
    if row is None:
        db.add(UsageCount(key=key, day=day, n=1))
    else:
        row.n = used + 1
    db.commit()
    return daily - used - 1
