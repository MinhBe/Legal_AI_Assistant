"""Phân loại dữ liệu A/B/C trước khi chọn model (design §4, contract G1).

A: tệp khách hàng tải lên — không bao giờ tới LLM bên ngoài.
B: có dữ liệu cá nhân — chỉ gửi đi sau khi đã che.
C: câu hỏi thuần pháp lý.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.gateway.pii import Masked, mask

CLASS_A, CLASS_B, CLASS_C = "A", "B", "C"


@dataclass
class GateResult:
    data_class: str
    message: str                                   # đã che
    history: list[dict]                            # bản sao đã che, cùng mapping
    mapping: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)


def classify(text: str, *, source: str = "chat") -> str:
    if source == "upload":
        return CLASS_A
    return CLASS_B if mask(text).counts else CLASS_C


def gate(message: str, history: list[dict] | None = None, *, source: str = "chat") -> GateResult:
    if classify(message, source=source) == CLASS_A:
        raise PermissionError("class A must not reach an external LLM")

    masked: Masked = mask(message)
    counts = dict(masked.counts)
    turns: list[dict] = []
    for raw in history or []:
        turn = dict(raw)
        if isinstance(turn.get("content"), str):
            part = mask(turn["content"], mapping=masked.mapping)
            for etype, n in part.counts.items():
                counts[etype] = counts.get(etype, 0) + n
            turn["content"] = part.text
        turns.append(turn)

    return GateResult(
        data_class=CLASS_B if counts else CLASS_C,
        message=masked.text,
        history=turns,
        mapping=masked.mapping,
        counts=counts,
    )
