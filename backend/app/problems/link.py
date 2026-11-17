"""Nối một bài toán với điều luật và án lệ — hoàn toàn cục bộ, không gọi LLM (AU2).

Điều luật: `search_nodes(facts + legal_question)` (hybrid/vector sẵn có).
Án lệ: nhúng tiêu đề trong `precedent_catalog` rồi so cosine; danh mục đổi (số dòng
hoặc `last_checked` lớn nhất) thì nhúng lại. Vector giữ trong bộ nhớ tiến trình.
"""

from __future__ import annotations

import math

from loguru import logger
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.rag.embeddings import embed, embed_one
from app.rag.search import search_nodes

PRECEDENT_MIN = 0.45
PROBLEM_MIN = 0.5

_CACHE_KEY: tuple[int, object] | None = None
_CACHE_ROWS: list[dict[str, str]] = []
_CACHE_VECS: list[list[float]] = []


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def link_articles(db: Session, text_query: str, *, top_k: int = 3) -> list[dict]:
    """Điều/khoản gần nhất với tình tiết + câu hỏi pháp lý."""
    if not text_query.strip():
        return []
    return [
        {"node_id": h["node_id"], "display": h["display"], "score": round(h["score"], 3)}
        for h in search_nodes(db, text_query, top_k=top_k)
    ]


def _catalogue(db: Session) -> tuple[list[dict[str, str]], list[list[float]]]:
    """Tiêu đề án lệ + vector, nhúng lại khi danh mục đổi."""
    global _CACHE_KEY, _CACHE_ROWS, _CACHE_VECS
    key = tuple(
        db.execute(
            text("SELECT count(*), max(last_checked) FROM precedent_catalog")
        ).one()
    )
    if key != _CACHE_KEY:
        rows = [
            dict(r._mapping)
            for r in db.execute(
                text("SELECT number, title, status, url FROM precedent_catalog")
            )
        ]
        vectors = (
            embed([row["title"] or row["number"] for row in rows]) if rows else []
        )
        _CACHE_KEY, _CACHE_ROWS, _CACHE_VECS = key, rows, vectors
    return _CACHE_ROWS, _CACHE_VECS


def link_precedents(
    db: Session, text_query: str, *, top_k: int = 3, minimum: float = PRECEDENT_MIN
) -> list[dict]:
    """Án lệ gần nhất (cosine ≥ `minimum`); lỗi/none thì trả rỗng, không chặn việc khác."""
    if not text_query.strip():
        return []
    try:
        rows, vectors = _catalogue(db)
    except Exception as exc:  # noqa: BLE001 — danh mục chưa có cũng không sao
        logger.warning("Không đọc được danh mục án lệ: {}", exc)
        return []
    if not rows:
        return []
    query_vec = embed_one(text_query)
    scored = [
        (row, _cosine(query_vec, vec))
        for row, vec in zip(rows, vectors, strict=True)
    ]
    scored.sort(key=lambda pair: -pair[1])
    return [
        {
            "number": row["number"],
            "title": row["title"],
            "status": row["status"],
            "url": row["url"],
            "similarity": round(score, 3),
        }
        for row, score in scored
        if score >= minimum
    ][:top_k]


def link_problems(db: Session, text_query: str, *, top_k: int = 2) -> list[dict]:
    """Bài toán ĐÃ ĐƯỢC LUẬT SƯ DUYỆT gần nhất (cosine trên tiêu đề + câu hỏi ≥ 0.5)."""
    if not text_query.strip():
        return []
    rows = db.execute(
        text(
            "SELECT id, title, legal_question, approved_by FROM case_problem"
            " WHERE status = 'da_duyet'"
        )
    ).all()
    if not rows:
        return []
    vectors = embed([f"{r.title} {r.legal_question}" for r in rows])
    query_vec = embed_one(text_query)
    scored = [
        (row, _cosine(query_vec, vec))
        for row, vec in zip(rows, vectors, strict=True)
    ]
    scored.sort(key=lambda pair: -pair[1])
    return [
        {
            "id": row.id,
            "title": row.title,
            "approved_by": row.approved_by,
            "similarity": round(score, 3),
        }
        for row, score in scored
        if score >= PROBLEM_MIN
    ][:top_k]
