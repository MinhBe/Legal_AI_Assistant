"""Xếp lại ứng viên bằng cross-encoder. Lỗi thì trả nguyên thứ tự cũ: rerank
không bao giờ được làm hỏng câu trả lời."""

from __future__ import annotations

import threading
from typing import Any

from loguru import logger

from app.config import get_settings

settings = get_settings()
_MODEL = None
_LOCK = threading.Lock()


def _model():
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from sentence_transformers import CrossEncoder

            _MODEL = CrossEncoder(settings.rerank_model, max_length=512)
    return _MODEL


def rerank_rows(query: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    try:
        pairs = [(query, f"{r.get('heading') or ''} {r['text'][:1500]}") for r in rows]
        scores = _model().predict(pairs, batch_size=8)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rerank lỗi, giữ thứ tự cũ: {}", exc)
        return rows
    for r, s in zip(rows, scores, strict=True):
        r["rerank_score"] = float(s)
    return sorted(rows, key=lambda r: -r["rerank_score"])
