"""Danh tính người gọi và kiểm tra quyền (AUTH1).

`current_user` luôn chạy được (kể cả khi tắt kiểm tra quyền); `require(perm)` mới là
cửa chặn: chưa đăng nhập -> 401, đã đăng nhập nhưng thiếu quyền -> 403.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from app.auth import roles, tokens
from app.config import get_settings

settings = get_settings()


def client_id(request: Request) -> str:
    """Mã trình duyệt cho khách vãng lai; thiếu header thì dùng IP."""
    given = (request.headers.get("x-client-id") or "").strip()
    if given:
        return given[:80]
    return request.client.host if request.client else "unknown"


def current_user(request: Request) -> dict:
    """{"username" | None, "role", "client_id"}; token thiếu/hỏng/quá hạn = anonymous."""
    auth = request.headers.get("authorization", "")
    data = tokens.verify(auth[7:].strip()) if auth.lower().startswith("bearer ") else None
    cid = client_id(request)
    if data is None:
        return {"username": None, "role": "anonymous", "client_id": cid}
    return {"username": data["username"], "role": data["role"], "client_id": cid}


def require(perm: str):
    """Dependency chặn theo quyền; bỏ qua hết khi AUTH_REQUIRED=false."""

    def dependency(user: dict = Depends(current_user)) -> dict:
        if not settings.auth_required or perm in roles.perms(user["role"]):
            return user
        if user["username"] is None:
            raise HTTPException(status_code=401, detail="Cần đăng nhập")
        raise HTTPException(
            status_code=403, detail=f"Tài khoản {user['role']} không có quyền này"
        )

    return dependency


def require_history(user: dict = Depends(current_user)) -> dict:
    """Lịch sử hội thoại trên máy chủ: vai trò có `history` (khách vãng lai thì không)."""
    if not settings.auth_required or roles.conf(user["role"])["history"]:
        return user
    raise HTTPException(status_code=403, detail=f"Tài khoản {user['role']} không có quyền này")
