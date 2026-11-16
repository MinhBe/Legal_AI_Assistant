"""Bảng vai trò và tài khoản demo (AUTH1) — tệp cấu hình DUY NHẤT để đổi quyền.

`daily: None` = không giới hạn số câu hỏi mỗi ngày. `ACCOUNTS` là tài khoản demo
của máy chạy nội bộ: mật khẩu = tên đăng nhập, xem mục cảnh báo trong README.
"""

from __future__ import annotations

ROLES: dict[str, dict] = {
    "anonymous": {"perms": {"chat", "calc"}, "daily": 10, "history": False, "cloud_first": False},
    "guest": {"perms": {"chat", "calc"}, "daily": 20, "history": True, "cloud_first": False},
    "guest_vip": {"perms": {"chat", "calc", "escalate"}, "daily": None, "history": True, "cloud_first": True},
    "user": {"perms": {"chat", "calc", "escalate"}, "daily": 50, "history": True, "cloud_first": False},
    "admin": {
        "perms": {"chat", "calc", "escalate", "upload", "graph", "review"},
        "daily": None,
        "history": True,
        "cloud_first": False,
    },
    "dev": {
        "perms": {"chat", "calc", "escalate", "upload", "graph", "review", "dev"},
        "daily": None,
        "history": True,
        "cloud_first": False,
    },
}

ACCOUNTS = {
    "admin": "admin", "dev": "dev", "user1": "user", "user2": "user", "user3": "user",
    "guest1": "guest_vip", "guest2": "guest", "guest3": "guest",
}  # mật khẩu = tên đăng nhập (demo)


def conf(role: str) -> dict:
    """Cấu hình của vai trò; vai trò lạ (token cũ) coi như anonymous."""
    return ROLES.get(role, ROLES["anonymous"])


def perms(role: str) -> set[str]:
    return conf(role)["perms"]
