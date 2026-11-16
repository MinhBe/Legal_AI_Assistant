"""Chỗ cắm API dữ liệu luật trả phí (LI3) — chỉ giao diện, mặc định TẮT.

Dành cho trường hợp Minh mua API doanh nghiệp của thuvienphapluat/luatvietnam: khi đó viết
một lớp thật hiện `LicensedSource` (tra theo số hiệu, tải toàn văn theo `doc_id`) và trả nó
từ `get_licensed()`. Hiện tại không có nhà cung cấp nào nên luôn trả None.

Không bao giờ ghi log khoá API; chỉ đọc tên biến môi trường `licensed_api_key_env`.
"""

from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from loguru import logger

from app.config import get_settings


@runtime_checkable
class LicensedSource(Protocol):
    """API dữ liệu luật trả phí: `search` theo số hiệu, `fetch` tệp toàn văn theo `doc_id`."""

    def search(self, number: str) -> list[dict[str, Any]]: ...

    def fetch(self, doc_id: str) -> bytes: ...


def get_licensed() -> LicensedSource | None:
    """Nguồn trả phí đang bật, hoặc None.

    Chỉ bật khi `licensed_api_provider` có giá trị VÀ biến môi trường do
    `licensed_api_key_env` đặt tên có khoá. Chưa có lớp hiện thực nào nên luôn trả None;
    khoá chỉ được kiểm tra sự tồn tại, không đọc vào biến, không ghi log.
    """
    settings = get_settings()
    if not settings.licensed_api_provider.strip():
        return None
    if not os.getenv(settings.licensed_api_key_env, "").strip():
        return None
    logger.info(
        "Đã cấu hình nguồn dữ liệu trả phí {} nhưng chưa có lớp hiện thực — bỏ qua.",
        settings.licensed_api_provider,
    )
    return None
