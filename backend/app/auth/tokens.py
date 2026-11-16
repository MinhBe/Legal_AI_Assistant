"""Token đăng nhập (AUTH1): base64url(`username|role|expires`) + "." + HMAC-SHA256.

Bí mật ký: AUTH_SECRET; để trống thì tạo ngẫu nhiên một lần ở `data/.auth_secret`
(mode 600, đã nằm trong .gitignore). Token sai chữ ký hoặc quá hạn coi như anonymous.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from pathlib import Path

from loguru import logger

from app.config import get_settings

TTL_HOURS = 12
SECRET_FILE = Path("/app/data/.auth_secret")

_secret: bytes | None = None


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def secret() -> bytes:
    global _secret
    if _secret is not None:
        return _secret
    configured = (get_settings().auth_secret or "").strip()
    if configured:
        _secret = configured.encode()
        return _secret
    if SECRET_FILE.exists():
        try:
            _secret = SECRET_FILE.read_text(encoding="utf-8").strip().encode()
        except OSError as exc:
            logger.warning("Không đọc được {}: {}", SECRET_FILE, exc)
    if not _secret:
        value = secrets.token_hex(32)
        try:
            SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
            SECRET_FILE.write_text(value, encoding="utf-8")
            SECRET_FILE.chmod(0o600)
        except OSError as exc:  # không ghi được thì vẫn chạy; token đổi sau mỗi lần khởi động
            logger.warning("Không ghi được {}: {}", SECRET_FILE, exc)
        _secret = value.encode()
    return _secret


def _sign(body: str) -> str:
    return _b64(hmac.new(secret(), body.encode(), hashlib.sha256).digest())


def issue(username: str, role: str, ttl_hours: float = TTL_HOURS) -> str:
    expires = int(time.time() + ttl_hours * 3600)
    body = _b64(f"{username}|{role}|{expires}".encode())
    return f"{body}.{_sign(body)}"


def verify(token: str) -> dict[str, str] | None:
    """{"username", "role"} khi chữ ký đúng và còn hạn, ngược lại None."""
    body, _, sig = (token or "").partition(".")
    if not body or not sig:
        return None
    if not hmac.compare_digest(_sign(body), sig):
        return None
    try:
        username, role, expires = _unb64(body).decode().split("|")
        if time.time() > float(expires):
            return None
    except (ValueError, UnicodeDecodeError):
        return None
    return {"username": username, "role": role}
