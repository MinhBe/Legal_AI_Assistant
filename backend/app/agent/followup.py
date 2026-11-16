"""Câu hỏi nối tiếp: "còn lao động nữ thì sao?" chỉ có nghĩa khi đọc kèm câu trước.

Truy xuất không đoán chắc câu nào là nối tiếp: khi có lịch sử, nó tìm CẢ câu hiện
tại lẫn câu trước + câu hiện tại rồi đan xen kết quả. Quy tắc chỉ quyết định danh
sách nào đứng trước, nên đoán sai cũng không làm mất kết quả của câu hỏi mới.
"""

from __future__ import annotations

import math
import re
from typing import Any

# từ nối thường gặp ở câu hỏi tiếp theo trong hội thoại tiếng Việt
_CUES = re.compile(
    r"^(còn|vậy|thế|nếu vậy|như vậy|trường hợp)\b"
    r"|\b(thì sao|ra sao|trường hợp (đó|này|trên)|như trên|điều (đó|này)|khoản (đó|này))\b",
    re.IGNORECASE,
)
_SHORT_WORDS = 5            # câu cụt kiểu "người quản lý thì?" gần như luôn là nối tiếp
_HISTORY_TURNS = 2          # số lượt hỏi gần nhất đưa vào prompt
_ANSWER_PREVIEW = 300       # cắt câu trả lời trước để prompt không phình

# Ngân sách prompt cho mô hình chạy trong máy (OLLAMA_CONTEXT_LENGTH=8192, chừa chỗ cho câu trả lời).
# Đếm bằng ký tự thay vì tokenizer: tokenizer Qwen2.5 cho văn bản luật ra thấp nhất 2,5 ký tự/token
# (trung vị 3,7), nên chia cho 2,5 luôn ước lượng dư số token.
CHARS_PER_TOKEN = 2.5
MAX_QUESTION_TOKENS = 3500
PROMPT_BUDGET_TOKENS = 6000
CONTEXT_RESERVE_TOKENS = 2400  # chỉ dẫn hệ thống + điều luật truy hồi: lớn nhất đo được 2.177 / 86 câu golden


def est_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


def history_budget(message: str) -> int:
    """Token còn lại cho lịch sử hội thoại sau khi giữ nguyên chỉ dẫn, điều luật và câu hỏi."""
    return max(0, PROMPT_BUDGET_TOKENS - CONTEXT_RESERVE_TOKENS - est_tokens(message))


def last_user_question(history: list[dict[str, str]] | None) -> str | None:
    for turn in reversed(history or []):
        if turn.get("role") == "user" and (turn.get("content") or "").strip():
            return turn["content"].strip()
    return None


def looks_like_follow_up(message: str) -> bool:
    text = message.strip()
    return bool(_CUES.search(text)) or len(text.split()) <= _SHORT_WORDS


def merge_hits(
    primary: list[dict[str, Any]], secondary: list[dict[str, Any]], k: int, *, primary_share: float = 0.75,
) -> list[dict[str, Any]]:
    """Giữ tối đa k kết quả: phần lớn chỗ cho danh sách ưu tiên, phần còn lại cho
    danh sách kia, bỏ trùng node_id. Đan xen 1:1 thì mỗi bên chỉ còn k/2 chỗ và
    cắt mất kết quả đúng nằm ở hạng 5 của danh sách ưu tiên."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def take(hits, limit):
        for h in hits:
            if len(out) >= limit:
                return
            if h["node_id"] not in seen:
                seen.add(h["node_id"])
                out.append(h)

    take(primary, round(k * primary_share))
    take(secondary, k)
    take(primary, k)          # bên kia hết kết quả thì lấp chỗ trống bằng bên ưu tiên
    return out


def search_with_history(db, message: str, history: list[dict[str, str]] | None, *, top_k: int, search):
    """Tìm theo câu hiện tại; có lịch sử thì tìm thêm theo câu trước + câu hiện tại."""
    alone = search(db, message, top_k=top_k)
    prev = last_user_question(history)
    if not prev:
        return alone
    combined = search(db, f"{prev} {message}", top_k=top_k)
    if looks_like_follow_up(message):
        return merge_hits(combined, alone, top_k)
    return merge_hits(alone, combined, top_k)


def history_block(history: list[dict[str, str]] | None, *, max_tokens: int | None = None) -> str:
    """Vài lượt hỏi–đáp gần nhất, để LLM hiểu đại từ và câu cụt.

    `max_tokens`: ước lượng token tối đa cho khối này (xem est_tokens)."""
    turns = [t for t in (history or []) if (t.get("content") or "").strip()]
    # lấy từ lượt hỏi thứ _HISTORY_TURNS tính từ cuối trở đi
    user_idx = [i for i, t in enumerate(turns) if t.get("role") == "user"]
    if not user_idx:
        return ""
    start = user_idx[-_HISTORY_TURNS] if len(user_idx) >= _HISTORY_TURNS else user_idx[0]
    lines = []
    for t in turns[start:]:
        who = "Người dùng" if t.get("role") == "user" else "Trợ lý"
        content = " ".join(t["content"].split())
        if who == "Trợ lý" and len(content) > _ANSWER_PREVIEW:
            content = content[:_ANSWER_PREVIEW] + "…"
        lines.append(f"{who}: {content}")
    if max_tokens is not None:
        budget = int(max_tokens * CHARS_PER_TOKEN)
        while len(lines) > 1 and len("\n".join(lines)) > budget:
            lines.pop(0)  # bỏ lượt cũ nhất trước
        if lines and len(lines[0]) > budget:  # lượt cuối vẫn quá dài: giữ phần đuôi
            lines = ["…" + lines[0][len(lines[0]) - budget + 1:]] if budget > 1 else []
    return "\n".join(lines)
