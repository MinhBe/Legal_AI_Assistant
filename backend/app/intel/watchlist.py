"""Danh sách ưu tiên (LI2) — tin nào đáng đọc trước.

`priority` 0..3: 3 = tiêu đề nói sửa đổi/thay thế/hướng dẫn/bãi bỏ một văn bản đã có trong
kho; 2 = có từ khoá lao động trọng tâm; 1 = chỉ là dấu hiệu lao động; 0 = còn lại.
Số hiệu lấy từ `legal_document.number` và số cơ sở của `doc_id` (`nd145_2020` → 145/2020).
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import LegalDocument
from app.intel import sources

PRIORITY_TERMS = (
    "lương tối thiểu",
    "tiền lương",
    "bảo hiểm xã hội",
    "bhxh",
    "bảo hiểm thất nghiệp",
    "việc làm",
    "bộ luật lao động",
    "bllđ",
    "hợp đồng lao động",
    "an toàn vệ sinh lao động",
    "công đoàn",
    "kỷ luật lao động",
    "thời giờ làm việc",
    "nghỉ ngơi",
    "trợ cấp",
)
#: động từ cho thấy văn bản đụng vào một văn bản đã có trong kho
AMEND_VERBS = ("sửa đổi", "thay thế", "hướng dẫn", "bãi bỏ")
#: "nd145_2020" → "145/2020"
_DOC_ID_NUMBER = re.compile(r"[a-z]+(\d+)_(\d{4})")


def corpus_numbers(db: Session) -> set[str]:
    """Số hiệu (và số cơ sở) của mọi văn bản trong kho, chữ thường."""
    numbers: set[str] = set()
    for number, doc_id in db.execute(select(LegalDocument.number, LegalDocument.doc_id)):
        if number:
            numbers.add(number.lower())
        found = _DOC_ID_NUMBER.fullmatch(doc_id or "")
        if found:
            numbers.add(f"{found.group(1)}/{found.group(2)}")
    return numbers


def _field(item: Any, key: str) -> str:
    value = item.get(key) if isinstance(item, dict) else getattr(item, key, None)
    return str(value or "")


def priority(item: Any, numbers: set[str] | None = None) -> int:
    """0..3 — càng cao càng đáng đọc trước."""
    text = " ".join(_field(item, key) for key in ("title", "number", "kind", "category")).lower()
    if numbers and any(verb in text for verb in AMEND_VERBS) and any(n in text for n in numbers):
        return 3
    if any(term in text for term in PRIORITY_TERMS):
        return 2
    hints = {key: _field(item, key) for key in ("title", "kind", "category")}
    if sources.labor_hint(hints):
        return 1
    return 0
