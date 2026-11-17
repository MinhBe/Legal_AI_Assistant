"""Sinh cặp hỏi–đáp từ dữ liệu CÔNG KHAI (KG1) — Dahl, mức dữ liệu C, cloud_first.

Một lời gọi cho mỗi bản ghi, JSON chặt kiểm bằng pydantic; sai thì thử lại MỘT lần kèm
lỗi kiểm. Không bao giờ gửi văn bản tải lên hay câu trả lời của khách: chỉ điều luật và
án lệ công khai.
"""

from __future__ import annotations

from typing import TypeVar

from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from app.llm.context import cloud_first_scope, data_class_scope
from app.llm.router import parse_json

MAX_COPY_CHARS = 4000

LAW_SYSTEM = """Bạn tạo dữ liệu huấn luyện cho trợ lý pháp luật lao động Việt Nam từ văn bản \
luật CÔNG KHAI.

Chỉ trả về đúng một đối tượng JSON, không thêm chữ nào khác:
{"pairs": [{"question": "...", "answer": "..."}], "time_trap": null}

- "question" là câu hỏi thực tế dài 20–600 ký tự của người lao động hoặc người sử dụng lao động.
- "answer" dài 80–2500 ký tự, tiếng Việt có dấu, chỉ dựa vào nội dung được cung cấp.
- Trong "answer" phải trích dẫn đúng nguyên văn dạng: Điều X khoản Y <tên văn bản> \
(<mốc hiệu lực>), chép đúng tên văn bản và mốc hiệu lực được cung cấp.
- Tuyệt đối không bịa điều, khoản, số hiệu văn bản, mốc hiệu lực, mức phạt hay thời hạn \
không có trong nội dung được cung cấp. Thiếu căn cứ thì trả {"pairs": [], "time_trap": null}.
- "time_trap" chỉ điền khi được yêu cầu; không yêu cầu thì để null.
- Câu trả lời phải nêu cụ thể nội dung điều khoản (mức, thời hạn, điều kiện, danh mục…), không \
trả lời chung chung kiểu "theo quy định" hay "các giấy tờ theo quy định".
- Nếu mốc hiệu lực ghi "hết hiệu lực", MỌI câu hỏi phải nêu rõ sự việc xảy ra trước ngày hết hiệu lực \
(ví dụ "tháng 6/2019", "năm 2020"); không được hỏi như chuyện hiện nay."""

PRECEDENT_SYSTEM = """Bạn tạo dữ liệu huấn luyện cho trợ lý pháp luật lao động Việt Nam từ một \
án lệ CÔNG KHAI.

Chỉ trả về đúng một đối tượng JSON, không thêm chữ nào khác:
{"summary": "...", "legal_situation": "...", "holding": "...", \
"qa": [{"question": "...", "answer": "..."}]}

- "summary" 2–3 câu; "legal_situation" là tình huống pháp lý; "holding" là nhận định của Toà.
- "qa": 1–2 cặp hỏi–đáp dài 20–600 / 80–2500 ký tự, tiếng Việt có dấu, trả lời có trích dẫn \
đúng dạng "Án lệ số <số>/<năm>/AL".
- Chỉ dùng nội dung được cung cấp; không bịa số án lệ, điều luật, mốc hiệu lực hay kết quả vụ án."""

RETRY = (
    "JSON trước không hợp lệ ({why}). Trả lại đúng một đối tượng JSON theo đúng quy tắc, "
    "không thêm chữ nào khác."
)

Schema = TypeVar("Schema", bound=BaseModel)


class QaPair(BaseModel):
    question: str
    answer: str


class LawPayload(BaseModel):
    pairs: list[QaPair] = Field(default_factory=list)
    time_trap: QaPair | None = None


class PrecedentPayload(BaseModel):
    summary: str = ""
    legal_situation: str = ""
    holding: str = ""
    qa: list[QaPair] = Field(default_factory=list)


def _ask(router, messages: list[dict[str, str]], schema: type[Schema]) -> tuple[Schema | None, str]:
    """Một lời gọi ở mức dữ liệu C (ưu tiên đám mây); lỗi thì trả (None, lý do)."""
    try:
        with data_class_scope("C"), cloud_first_scope(True):
            raw = router.chat(messages, task="bulk", temperature=0.7).text
        return schema.model_validate(parse_json(raw)), ""
    except (ValidationError, ValueError, TypeError, KeyError) as exc:
        logger.warning("JSON sinh dữ liệu không hợp lệ: {}", exc)
        return None, str(exc)[:200]
    except Exception as exc:  # noqa: BLE001 — lỗi nhà cung cấp không được làm hỏng cả lô
        logger.warning("Lời gọi sinh dữ liệu lỗi: {}", exc)
        return None, str(exc)[:200]


def _parse(router, messages: list[dict[str, str]], schema: type[Schema]) -> Schema | None:
    payload, why = _ask(router, messages, schema)
    if payload is None:
        retry = [*messages, {"role": "user", "content": RETRY.format(why=why)}]
        payload, _ = _ask(router, retry, schema)
    return payload


def _pairs(items: list[QaPair]) -> list[dict[str, str]]:
    return [
        {"question": p.question.strip(), "answer": p.answer.strip()}
        for p in items
        if p.question.strip() and p.answer.strip()
    ]


def _law_user(record: dict, n: int) -> str:
    label = record["doc_label"]
    tag = record["time_tag"]
    validity = record.get("validity") or tag
    clause = f" khoản {record['clause_no']}" if record.get("clause_no") else ""
    citation = f"Điều {record['article_no']}{clause} {label} ({validity})"
    lines = [
        f"Văn bản: {label}",
        f"Mốc hiệu lực: {tag}",
        f"Điều {record['article_no']}{clause}",
        "Nội dung:",
        record["text"][:MAX_COPY_CHARS],
        "",
        f"Viết {n} cặp hỏi–đáp tình huống thực tế cho điều khoản này.",
        f"Trích dẫn đúng dạng: {citation}.",
    ]
    if record.get("time_trap"):
        lines.append(
            "Thêm 1 cặp vào \"time_trap\" cho tình huống xảy ra TRƯỚC 01/01/2021, trong đó "
            "ngày xảy ra sự việc quyết định văn bản áp dụng; vẫn trích dẫn đúng dạng trên."
        )
    return "\n".join(lines)


def law_pairs(router, record: dict, n: int = 3) -> list[dict[str, str]]:
    """Sinh `n` cặp hỏi–đáp (+ cặp bẫy thời gian khi áp dụng) cho một điều/khoản."""
    messages = [
        {"role": "system", "content": LAW_SYSTEM},
        {"role": "user", "content": _law_user(record, n)},
    ]
    payload = _parse(router, messages, LawPayload)
    if payload is None:
        return []
    out = _pairs(payload.pairs)
    if payload.time_trap:
        out += _pairs([payload.time_trap])
    return out


def precedent_card(router, record: dict) -> list[dict[str, str]]:
    """Sinh cặp hỏi–đáp từ toàn văn án lệ đã được duyệt (không có toàn văn thì bỏ qua)."""
    body = (record.get("text") or "").strip()
    if not record.get("has_full_text") or not body:
        return []
    messages = [
        {"role": "system", "content": PRECEDENT_SYSTEM},
        {
            "role": "user",
            "content": f"{record['precedent_no']} — {record.get('title', '')}\n\n"
            f"Nội dung:\n{body[:MAX_COPY_CHARS * 2]}",
        },
    ]
    payload = _parse(router, messages, PrecedentPayload)
    return _pairs(payload.qa) if payload else []
