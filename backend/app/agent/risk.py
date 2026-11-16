"""Bộ chấm rủi ro bằng quy tắc (R1, design §9.1, §15.3).

Điểm rủi ro = tổng trọng số các lý do; ca có điểm >= `QUEUE_THRESHOLD` hoặc lý do
+∞ thì vào hàng đợi luật sư. Thuần code, không gọi LLM.

    r = score(question, events)   # {"score", "queue", "reasons"}
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from app.agent.guard import normalize

QUEUE_THRESHOLD = 3
LIMITATION_DAYS = 365
# "11 tháng trước ngày tư vấn" xấp xỉ 334 ngày; chặn trên là mốc 1 năm.
_NEAR_LIMITATION_MIN_DAYS = LIMITATION_DAYS - 31

_HIGH_STAKES = (
    "sa thai", "duoi viec", "cham dut hop dong", "boi thuong",
    "tro cap thoi viec", "ky luat",
)
# Khớp nguyên cụm từ trên chữ đã bỏ dấu: "bieu" trần sẽ dính "biểu mẫu", "đại biểu";
# "điều tra" trần dính "điều tra tai nạn lao động" (việc lao động bình thường).
_OUT_OF_SCOPE_RE = re.compile(
    r"\b(qua tang|qua bieu|bieu xen|hoi lo|dut lot|khoi to|co quan dieu tra|dieu tra hinh su"
    r"|bi dieu tra|dang bi dieu tra)\b"
)
_DISTRESS_RE = re.compile(r"\b(tu tu|muon chet|khong thiet song|tuyet vong)\b")


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _scan(events: list[tuple[str, object]]) -> tuple[str, set[str], dict, dict, dict | None]:
    """Câu trả lời, các node đã trích, `done`, `timeframe`, `verifier` từ luồng sự kiện."""
    chunks: list[str] = []
    cites: set[str] = set()
    done: dict = {}
    tf: dict = {}
    verifier: dict | None = None
    for event, data in events:
        if not isinstance(data, dict):
            continue
        if event == "token":
            chunks.append(data.get("text") or "")
        elif event == "citation":
            if data.get("node_id"):
                cites.add(data["node_id"])
        elif event == "section":
            for c in data.get("citations") or []:
                if isinstance(c, dict) and c.get("node_id"):
                    cites.add(c["node_id"])
        elif event == "done":
            done = data
        elif event == "timeframe":
            tf = data
        elif event == "verifier":
            verifier = data
    return "".join(chunks), cites, done, tf, verifier


def score(question: str, events: list[tuple[str, object]]) -> dict:
    """{"score": int | "inf", "queue": bool, "reasons": [{"code", "weight", "message"}]}."""
    q = normalize(question or "")
    answer, cites, done, tf, verifier = _scan(events)

    reasons: list[dict] = []

    def add(code: str, weight: int | str, message: str) -> None:
        reasons.append({"code": code, "weight": weight, "message": message})

    if any(w in q or w in normalize(answer) for w in _HIGH_STAKES):
        add("high_stakes", 3,
            "Giá trị/hậu quả lớn (sa thải, chấm dứt hợp đồng, bồi thường, kỷ luật)")

    event, advice = _day(tf.get("event_date")), _day(tf.get("advice_date"))
    near = bool(event and advice and _NEAR_LIMITATION_MIN_DAYS <= (advice - event).days <= LIMITATION_DAYS)
    if near or "thoi hieu" in q:
        add("near_limitation", 3,
            "Gần mốc thời hiệu 1 năm — cần luật sư xác nhận")

    if tf.get("transition_rules") or tf.get("upcoming"):
        add("transition", 2,
            "Có điều khoản chuyển tiếp hoặc văn bản đang chờ sửa đổi liên quan")

    confidence = done.get("confidence")
    if len(cites) < 2 or (isinstance(confidence, int | float) and confidence < 0.6):
        add("low_retrieval", 2,
            "Độ chắc truy xuất thấp (ít căn cứ trích dẫn hoặc độ tin cậy thấp)")

    if verifier is not None and verifier.get("ok") is False:
        add("verifier", 3,
            "Verifier báo lỗi căn cứ (điều luật không hiệu lực hoặc trích không khớp)")

    if any("xu phat" in normalize(f) for f in tf.get("flags") or [] if isinstance(f, str)):
        add("sanction_no_rule", 3,
            "Xử phạt hành chính chưa có quy tắc chuyển tiếp rõ ràng")

    if done.get("category") == "out_of_corpus" or _OUT_OF_SCOPE_RE.search(q):
        add("out_of_scope", "inf",
            "Ngoài phạm vi kho văn bản (quà tặng, hối lộ, điều tra) — chuyển luật sư chuyên môn")

    if _DISTRESS_RE.search(q):
        add("distress", "inf",
            "Khách đang khủng hoảng cảm xúc — chuyển người ngay")

    if any(r["weight"] == "inf" for r in reasons):
        total: int | str = "inf"
    else:
        total = sum(r["weight"] for r in reasons)
    queue = total == "inf" or total >= QUEUE_THRESHOLD
    return {"score": total, "queue": queue, "reasons": reasons}
