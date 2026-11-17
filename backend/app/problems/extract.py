"""Bản chép lời đã che PII / ghi chú nhóm -> "bài toán" (AU2).

Một lời gọi mô hình cho mỗi đoạn, JSON chặt, kiểm bằng pydantic: mục hỏng bị bỏ và
được thử lại MỘT lần kèm lỗi kiểm. Mặc định chạy trong `data_class_scope("A")` (mô
hình trong máy). Chỉ khi tệp được bật công tắc Dahl VÀ văn bản gửi đi là bản đã che
thì mới chạy mức C + `cloud_first_scope(True)`; `assert_masked` chặn nếu còn giá trị gốc.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.llm.context import cloud_first_scope, data_class_scope
from app.llm.router import parse_json

SYSTEM = """Bạn rút "bài toán" pháp lý lao động từ một đoạn bản chép lời buổi tư vấn \
hoặc ghi chú của nhóm làm việc.

Chỉ trả về đúng một đối tượng JSON, không thêm chữ nào khác:
{"problems": [{"title": "...", "facts": "...", "legal_question": "...",
"suggested_approach": "...", "options": [{"name": "...", "pros": "...", "cons": "..."}],
"cited_articles": ["..."], "uncertain_points": ["..."],
"start_ts": 0, "end_ts": 0}]}

- Chỉ dùng thông tin CÓ TRONG đoạn; không suy đoán thêm sự kiện, không thêm người.
- "title" ngắn (dưới 15 từ); "facts" là tình tiết như người nói kể; "legal_question" là
  câu hỏi pháp lý cần trả lời.
- "suggested_approach" là điều người nói KHUYẾN NGHỊ, không phải kết luận của bạn.
- "cited_articles" chép nguyên văn dẫn chiếu người nói đã nêu; TUYỆT ĐỐI không tự thêm
  hay tự nghĩ ra điều luật; không có thì để [].
- Điểm nào pháp lý còn đáng ngờ, thiếu dữ kiện hoặc cần luật sư xác nhận thì ghi vào
  "uncertain_points"; không tự kết luận thay luật sư.
- "start_ts"/"end_ts" là giây trong bản ghi âm; không rõ thì để 0.
- Viết bằng tiếng Việt. Đoạn không có bài toán nào thì trả {"problems": []}."""

RETRY = (
    "JSON trước không hợp lệ ({why}). Trả lại đúng một đối tượng JSON theo đúng quy tắc, "
    "không thêm chữ nào khác."
)


class Option(BaseModel):
    name: str
    pros: str = ""
    cons: str = ""


class Problem(BaseModel):
    title: str
    facts: str
    legal_question: str
    suggested_approach: str = ""
    options: list[Option] = Field(default_factory=list)
    cited_articles: list[str] = Field(default_factory=list)
    uncertain_points: list[str] = Field(default_factory=list)
    start_ts: float | None = None
    end_ts: float | None = None


def assert_masked(text: str, mapping: dict[str, str]) -> None:
    """Chặn gửi Dahl nếu bản gửi đi còn bất kỳ giá trị gốc nào trong ánh xạ che PII."""
    if any(value and value in text for value in mapping.values()):
        # không ghi giá trị lọt vào thông báo lỗi hay log
        raise ValueError("Bản gửi Dahl còn giá trị gốc chưa được che")


def _ask(router, messages: list[dict[str, str]], *, allow_dahl: bool) -> dict[str, Any] | None:
    """Một lời gọi mô hình trong đúng mức dữ liệu; lỗi thì trả None, không ném ra ngoài."""
    cloud = cloud_first_scope(True) if allow_dahl else nullcontext()
    try:
        with data_class_scope("C" if allow_dahl else "A"), cloud:
            data = parse_json(router.chat(messages, task="route", temperature=0.0).text)
    except Exception as exc:  # noqa: BLE001 — một đoạn hỏng không được làm hỏng cả tệp
        logger.warning("Rút bài toán lỗi: {}", exc)
        return None
    return data if isinstance(data, dict) else None


def _items(
    data: dict[str, Any] | None, start_ts: float, end_ts: float
) -> tuple[list[dict[str, Any]], str]:
    """Kiểm từng mục; trả (mục hợp lệ, mô tả lỗi kiểm để thử lại)."""
    raw = data.get("problems") if isinstance(data, dict) else None
    out: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, item in enumerate(raw or [], 1):
        try:
            problem = Problem.model_validate(item)
        except ValidationError as exc:
            errors.append(f"mục {index}: {exc.errors()[0]['msg']}")
            continue
        d = problem.model_dump()
        d["start_ts"] = start_ts if d["start_ts"] is None else d["start_ts"]
        d["end_ts"] = end_ts if d["end_ts"] is None else d["end_ts"]
        out.append(d)
    return out, "; ".join(errors)


def extract(
    router,
    text: str,
    *,
    start_ts: float = 0.0,
    end_ts: float = 0.0,
    allow_dahl: bool = False,
    mapping: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Rút bài toán từ một đoạn. `mapping` là ánh xạ che PII của bản chép lời."""
    if not text.strip():
        return []
    if allow_dahl:
        assert_masked(text, mapping or {})
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": text},
    ]
    items, why = _items(_ask(router, messages, allow_dahl=allow_dahl), start_ts, end_ts)
    if not items and why:
        retry = [*messages, {"role": "user", "content": RETRY.format(why=why)}]
        items, _ = _items(_ask(router, retry, allow_dahl=allow_dahl), start_ts, end_ts)
    return items
