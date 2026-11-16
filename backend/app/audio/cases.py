"""Bản chép lời -> ca tư vấn (tình huống, câu hỏi, trả lời, điều luật) (AU1).

Một lời gọi mô hình trong máy cho mỗi đoạn, trong `data_class_scope("A")` — mức A
không bao giờ ra đám mây. Mục nào thiếu trường bắt buộc thì bỏ, không đoán thêm.
"""

from __future__ import annotations

from app.llm.context import data_class_scope

SYSTEM = """Bạn rút thông tin từ một đoạn bản chép lời buổi tư vấn pháp luật lao động.

Chỉ trả về đúng một đối tượng JSON, không thêm chữ nào khác:
{"cases": [{"situation": "...", "question": "...", "answer": "...", "articles": ["..."]}]}

- Mỗi ca là một câu hỏi người lao động/người sử dụng lao động hỏi và câu trả lời trong đoạn.
- Chỉ ghi điều có trong đoạn; không suy đoán thêm sự kiện, không tự thêm hay tự tính ngày
  hiệu lực của văn bản.
- "articles" chép nguyên văn dẫn chiếu xuất hiện trong đoạn, ví dụ
  "khoản 1 Điều 36 Bộ luật Lao động"; không có thì để [].
- Đoạn chỉ chào hỏi, trao đổi lặt vặt, không có ca nào thì trả {"cases": []}."""


def extract(router, text: str) -> list[dict]:
    """Gọi mô hình một lần; trả danh sách ca tư vấn hợp lệ."""
    if not text.strip():
        return []
    with data_class_scope("A"):
        data = router.extract_json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}],
            task="route",
        )
    items = data.get("cases") if isinstance(data, dict) else data
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        fields = {k: str(item.get(k) or "").strip() for k in ("situation", "question", "answer")}
        if not all(fields.values()):
            continue
        articles = item.get("articles") or []
        if isinstance(articles, str):
            articles = [articles]
        out.append({**fields, "articles": [str(a).strip() for a in articles if str(a).strip()]})
    return out
