"""Ngôn ngữ của câu hỏi và chỉ dẫn trả lời (contract ML1).

Câu hỏi có thể viết bằng tiếng Anh/Nhật/Trung; câu trả lời viết bằng đúng ngôn ngữ
đó, còn số điều/khoản và tên văn bản luật giữ nguyên tiếng Việt.
"""

from __future__ import annotations

import re

from app.agent.guard import vi_diacritic_ratio

_KANA = re.compile(r"[\u3040-\u30ff]")  # hiragana + katakana
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_ASCII = re.compile(r"[A-Za-z]")

NAMES = {"vi": "tiếng Việt", "en": "tiếng Anh", "ja": "tiếng Nhật", "zh": "tiếng Trung"}


def detect(text: str) -> str:
    """Đoán ngôn ngữ câu hỏi bằng quy tắc, không cần gói nào: "vi" | "en" | "ja" | "zh"."""
    if _KANA.search(text):
        return "ja"
    letters = [c for c in text if c.isalpha()]
    if letters and len(_HAN.findall(text)) / len(letters) >= 0.2:
        return "zh"
    if vi_diacritic_ratio(text) >= 0.03:
        return "vi"
    if letters and len(_ASCII.findall(text)) / len(letters) >= 0.6:
        return "en"
    return "vi"


def answer_instruction(lang: str) -> str:
    """Một dòng thêm vào prompt trả lời; rỗng khi câu hỏi bằng tiếng Việt."""
    if lang == "vi":
        return ""
    name = NAMES.get(lang, NAMES["vi"])
    return (
        f"Viết `summary` và `detail` của mọi mục bằng {name}. Giữ nguyên số điều/khoản và tên "
        "văn bản tiếng Việt (ví dụ «Điều 25 Bộ luật Lao động 2019») rồi dịch ngắn trong ngoặc."
    )
