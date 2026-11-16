"""Tài khoản demo (AUTH1): chỉ lưu băm PBKDF2-HMAC-SHA256, không lưu mật khẩu gốc."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from sqlalchemy.orm import Session

from app.auth.roles import ACCOUNTS
from app.db.models import AppUser

ITERATIONS = 200_000


def hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), ITERATIONS
    ).hex()


def seed(db: Session) -> None:
    """Tạo tài khoản còn thiếu; đổi vai trò khi roles.py đã đổi."""
    changed = False
    for username, role in ACCOUNTS.items():
        row = db.get(AppUser, username)
        if row is None:
            salt = secrets.token_hex(16)
            db.add(
                AppUser(username=username, role=role, salt=salt,
                        pw_hash=hash_password(username, salt))
            )
            changed = True
        elif row.role != role:
            row.role = role
            changed = True
    if changed:
        db.commit()


def verify(db: Session, username: str, password: str) -> AppUser | None:
    row = db.get(AppUser, username)
    if row is None:
        return None
    if not hmac.compare_digest(row.pw_hash, hash_password(password, row.salt)):
        return None
    return row
