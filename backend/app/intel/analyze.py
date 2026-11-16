"""Phân tích tin mới bằng Dahl (LI1) — chỉ dữ liệu công khai, mức C.

Mỗi tin được đánh giá: có liên quan lao động không, thay đổi gì, ảnh hưởng mấy, đưa cho
luật sư xử lý thế nào. Ngữ cảnh gửi đi chỉ là dữ liệu công khai nên chạy trong
`data_class_scope("C")` + `cloud_first_scope(True)` — tuyến Dahl được thử trước.

Mô hình KHÔNG được tự nghĩ ra ngày hiệu lực hay số hiệu văn bản: prompt nói rõ chỉ dùng dữ
liệu được cung cấp, và code lọc `affected_nodes` về đúng các node đã truy hồi (design §1, §5).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IntelItem, LegalDocument
from app.intel import store
from app.llm.context import cloud_first_scope, data_class_scope
from app.llm.router import get_router
from app.rag.search import search_nodes

MAX_PER_RUN = 10
MAX_TITLE_CHARS = 400
MAX_NODE_CHARS = 200


class Routing(BaseModel):
    model_config = ConfigDict(extra="forbid")

    queue: str
    action: Literal["nạp ngay", "theo dõi", "bỏ qua"]
    kg_updates: list[str] = Field(default_factory=list)


class Analysis(BaseModel):
    """Đầu ra đúng schema; `extra="forbid"` để mô hình thêm trường lạ là hỏng ngay."""

    model_config = ConfigDict(extra="forbid")

    relevant_labor: bool
    topic: str
    summary: str
    what_changes: str
    amends: list[str] = Field(default_factory=list)
    replaces: list[str] = Field(default_factory=list)
    affected_nodes: list[str] = Field(default_factory=list)
    effective_date: str | None = None
    impact: Literal["cao", "trung bình", "thấp"]
    impact_reason: str
    routing: Routing
    needs_full_text: bool
    confidence: float

    @field_validator("effective_date")
    @classmethod
    def _iso_only(cls, value: str | None) -> str | None:
        """Chỉ nhận ngày ISO có thật; còn lại coi như không biết."""
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10]).isoformat()
        except ValueError:
            return None


_RULES = """Bạn là chuyên gia pháp luật lao động Việt Nam. Đánh giá một văn bản/án lệ MỚI và
định tuyến việc cập nhật kho luật. Trả lời bằng tiếng Việt, CHỈ một object JSON.

QUY TẮC, theo thứ tự:
1. Chỉ dựa trên dữ liệu được cung cấp bên dưới (tiêu đề, số hiệu, loại, ngày, danh sách văn
   bản trong kho, các điều khoản gợi ý). Không dùng trí nhớ, không suy đoán nội dung.
2. summary: tối đa 3 câu, chỉ từ tiêu đề/số hiệu/loại/ngày; nói rõ khi chưa có toàn văn.
3. what_changes: thay đổi gì so với hiện tại; chưa có toàn văn thì ghi
   "chưa rõ — cần toàn văn".
4. amends / replaces: chỉ số hiệu văn bản XUẤT HIỆN trong dữ liệu được cung cấp. Không có thì [].
5. affected_nodes: chỉ chọn trong danh sách node_id được cung cấp; không chọn được thì [].
6. effective_date: chỉ điền "yyyy-mm-dd" khi ngày đó có trong dữ liệu; không biết để null.
7. impact: "cao" | "trung bình" | "thấp"; impact_reason 1-2 câu.
8. routing.queue: nhóm việc cho luật sư (ví dụ "tiền lương", "bảo hiểm xã hội", "cần đối
   chiếu"); routing.action: "nạp ngay" | "theo dõi" | "bỏ qua"; routing.kg_updates: các việc
   cập nhật kho (ví dụ "thêm văn bản", "nối khoản 1 Điều 90").
9. needs_full_text: true khi chưa có toàn văn để kết luận.
10. confidence: 0-1; càng ít dữ liệu càng thấp.
11. Không biết thì để null / [] và hạ confidence. Tuyệt đối không thêm chữ ngoài JSON.

Schema JSON:
{"relevant_labor": bool, "topic": str, "summary": str, "what_changes": str,
 "amends": [str], "replaces": [str], "affected_nodes": [str],
 "effective_date": str|null, "impact": "cao"|"trung bình"|"thấp", "impact_reason": str,
 "routing": {"queue": str, "action": "nạp ngay"|"theo dõi"|"bỏ qua", "kg_updates": [str]},
 "needs_full_text": bool, "confidence": float}"""

_RETRY = (
    "Lần trước JSON không hợp lệ: {error}. Trả lại đúng một object JSON theo schema, "
    "không thêm chữ nào khác."
)


def _corpus(db: Session, limit: int = 200) -> list[dict[str, Any]]:
    rows = db.execute(
        select(
            LegalDocument.doc_id,
            LegalDocument.number,
            LegalDocument.title,
            LegalDocument.effective_date,
            LegalDocument.expired_date,
        )
        .order_by(LegalDocument.doc_id)
        .limit(limit)
    ).all()
    return [
        {
            "doc_id": row[0],
            "number": row[1],
            "title": row[2],
            "effective_date": row[3].isoformat() if row[3] else None,
            "expired_date": row[4].isoformat() if row[4] else None,
        }
        for row in rows
    ]


def hits(db: Session, item: IntelItem, top_k: int = 5) -> list[dict[str, Any]]:
    """Các điều khoản gần nhất với tiêu đề tin (rỗng nếu truy hồi lỗi)."""
    try:
        return search_nodes(db, item.title, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 — truy hồi hỏng thì vẫn phân tích được
        logger.warning("Không truy hồi được node cho tin {}: {}", item.id, exc)
        return []


def _messages(db: Session, item: IntelItem, found: list[dict[str, Any]]) -> list[dict[str, str]]:
    context = {
        "tin_moi": {
            "title": item.title[:MAX_TITLE_CHARS],
            "number": item.number,
            "kind": item.kind,
            "category": item.category,
            "url": item.url,
            "listed_date": item.listed_date.isoformat() if item.listed_date else None,
            "source": item.source,
        },
        "van_ban_trong_kho": _corpus(db),
        "dieu_khoan_goi_y": [
            {
                "node_id": row.get("node_id"),
                "display": row.get("display"),
                "text": (row.get("text") or "")[:MAX_NODE_CHARS],
            }
            for row in found
        ],
    }
    return [
        {"role": "system", "content": _RULES},
        {
            "role": "user",
            "content": "Dữ liệu (JSON):\n" + json.dumps(context, ensure_ascii=False),
        },
    ]


def _brief(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return f"{exc.__class__.__name__}: {text}"[:300]


def analyse(db: Session, item: IntelItem) -> bool:
    """Phân tích (hoặc phân tích lại) một tin. Lỗi thì ghi `error`, status giữ `new`."""
    found = hits(db, item)
    allowed = {row.get("node_id") for row in found}
    messages = _messages(db, item, found)
    error = ""
    with data_class_scope("C"), cloud_first_scope(True):
        router = get_router()
        for attempt in (1, 2):  # sai schema/JSON thì nhắc lỗi và thử lại đúng một lần
            try:
                result = Analysis.model_validate(router.extract_json(messages, task="route"))
            except Exception as exc:  # noqa: BLE001 — JSON hỏng hoặc sai schema
                error = _brief(exc)
                logger.warning("Tin {} phân tích hỏng (lần {}): {}", item.id, attempt, error)
                messages = [*messages, {"role": "user", "content": _RETRY.format(error=error)}]
                continue
            data = result.model_dump()
            data["affected_nodes"] = [n for n in data["affected_nodes"] if n in allowed]
            store.save_analysis(db, item, data)
            return True
    store.set_error(db, item, error)
    return False


def analyse_pending(db: Session) -> dict[str, int]:
    """Phân tích tin mới: bỏ qua tin không liên quan lao động hoặc đã có trong kho, tối đa
    MAX_PER_RUN lời gọi mỗi lượt (phần còn lại để lần sau)."""
    counts = {"analysed": 0, "skipped": 0, "failed": 0}
    for item in db.scalars(select(IntelItem).where(IntelItem.status == "new")):
        if not item.labor_hint or item.in_corpus:
            item.status = "skipped"
            counts["skipped"] += 1
            db.commit()
            continue
        if counts["analysed"] + counts["failed"] >= MAX_PER_RUN:
            continue  # để lượt quét sau
        if analyse(db, item):
            counts["analysed"] += 1
        else:
            counts["failed"] += 1
    return counts
