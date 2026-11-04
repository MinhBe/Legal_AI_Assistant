"""Tìm kiếm hybrid trên Postgres: vector (pgvector) + từ khóa (trigram/ILIKE).

Mặc định chỉ lấy node còn hiệu lực (effective_to IS NULL). Lọc theo ngày ở M4.
Chế độ truy hồi chọn bằng search_mode (vector | bm25 | hybrid); mặc định vector.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.rag.bm25 import search_bm25
from app.rag.embeddings import embed_one

settings = get_settings()


_DOC_KIND = {"nghi_dinh": "Nghị định", "thong_tu": "Thông tư", "nghi_quyet": "Nghị quyết"}
_doc_names: dict[str, str] = {}


def _load_doc_names() -> None:
    from app.db.base import engine

    with engine.connect() as c:
        rows = c.execute(text("SELECT doc_id, title, number, doc_type FROM legal_document")).all()
    for doc_id, title, number, doc_type in rows:
        # luật có tiêu đề ngắn sẵn; văn bản dưới luật thì tiêu đề dài, dùng loại + số hiệu
        if doc_type in _DOC_KIND and number:
            _doc_names[doc_id] = f"{_DOC_KIND[doc_type]} {number}"
        else:
            _doc_names[doc_id] = title or doc_id


def doc_name(doc_id: str) -> str:
    """Tên văn bản để hiển thị, ví dụ "Bộ luật Lao động 2019" thay cho mã blld2019."""
    if doc_id not in _doc_names:
        try:
            _load_doc_names()   # lần đầu, hoặc vừa nạp thêm văn bản mới
        except Exception:
            return doc_id
        _doc_names.setdefault(doc_id, doc_id)   # mã lạ: không truy vấn lại mỗi lần
    return _doc_names[doc_id]


def _display(row: dict[str, Any]) -> str:
    parts = []
    if row.get("article_no"):
        parts.append(f"Điều {row['article_no']}")
    if row.get("clause_no"):
        parts.append(f"Khoản {row['clause_no']}")
    if row.get("point_letter"):
        parts.append(f"Điểm {row['point_letter']}")
    head = " ".join(parts) if parts else row["node_id"]
    return f"{head} ({doc_name(row['doc_id'])})"


_COLS = "node_id, doc_id, level, article_no, clause_no, point_letter, heading, text"


def _vector(db: Session, query: str, k: int, eff_clause: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    """Vector cosine nếu đã có embedding; chưa có thì lùi về trigram/ILIKE (như M0-M4)."""
    has_vec = db.execute(
        text("SELECT count(*) FROM legal_node WHERE embedding IS NOT NULL")
    ).scalar() or 0
    p = {**params, "k": k}
    if has_vec:
        p["vec"] = str(embed_one(query))
        sql = text(
            f"""
            SELECT {_COLS}, 1 - (embedding <=> CAST(:vec AS vector)) AS score
            FROM legal_node
            WHERE embedding IS NOT NULL {eff_clause}
            ORDER BY embedding <=> CAST(:vec AS vector)
            LIMIT :k
            """
        )
    else:
        sql = text(
            f"""
            SELECT {_COLS}, similarity(text, :q) AS score
            FROM legal_node
            WHERE text ILIKE '%' || :q || '%' {eff_clause}
            ORDER BY score DESC
            LIMIT :k
            """
        )
    return [dict(r._mapping) for r in db.execute(sql, p)]


def _allowed_ids(db: Session, eff_clause: str, params: dict[str, Any]) -> set[str]:
    """Các node đúng điều kiện hiệu lực; BM25 chỉ được xếp hạng trong tập này."""
    rows = db.execute(text(f"SELECT node_id FROM legal_node WHERE true {eff_clause}"), params)
    return {r[0] for r in rows}


def _fetch(db: Session, ids: list[str]) -> list[dict[str, Any]]:
    """Lấy node theo id, giữ đúng thứ tự của `ids`."""
    if not ids:
        return []
    rows = db.execute(
        text(f"SELECT {_COLS} FROM legal_node WHERE node_id = ANY(:ids)"), {"ids": ids}
    )
    by_id = {r._mapping["node_id"]: dict(r._mapping) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def search_nodes(
    db: Session,
    query: str,
    *,
    top_k: int = 5,
    as_of: date | None = None,
    only_in_force: bool = True,
    mode: str | None = None,
    rerank: bool | None = None,
) -> list[dict[str, Any]]:
    """Truy hồi node luật. mode: vector (mặc định) | bm25 | hybrid (RRF vector + BM25).
    rerank: xếp lại bằng cross-encoder sau khi truy hồi (mặc định theo settings)."""
    mode = mode or settings.search_mode
    rerank = settings.rerank_enabled if rerank is None else rerank
    pool = max(top_k, settings.rerank_top_n) if rerank else top_k

    n = db.execute(text("SELECT count(*) FROM legal_node")).scalar() or 0
    if n == 0:
        return []

    eff_clause = ""
    params: dict[str, Any] = {"q": query}
    if as_of is not None:
        eff_clause = " AND effective_from <= :d AND (effective_to IS NULL OR effective_to > :d)"
        params["d"] = as_of
    elif only_in_force:
        eff_clause = " AND effective_to IS NULL"

    if mode == "vector":
        rows = _vector(db, query, pool, eff_clause, params)
    elif mode == "bm25":
        allowed = _allowed_ids(db, eff_clause, params)
        hits = search_bm25(db, query, pool, allowed)
        scores = dict(hits)
        rows = _fetch(db, [i for i, _ in hits])
        for r in rows:
            r["score"] = scores.get(r["node_id"], 0.0)
    elif mode == "hybrid":
        cand = settings.hybrid_candidates
        allowed = _allowed_ids(db, eff_clause, params)
        vec = _vector(db, query, cand, eff_clause, params)
        bm = search_bm25(db, query, cand, allowed)
        fused: dict[str, float] = {}
        for ranked in ([r["node_id"] for r in vec], [i for i, _ in bm]):
            for rank, node_id in enumerate(ranked, 1):
                fused[node_id] = fused.get(node_id, 0.0) + 1 / (settings.rrf_k + rank)
        ids = sorted(fused, key=lambda i: -fused[i])[:pool]
        vscore = {r["node_id"]: r["score"] for r in vec}
        rows = _fetch(db, ids)
        for r in rows:
            r["rank_score"] = fused[r["node_id"]]
            r["score"] = float(vscore.get(r["node_id"], 0.0))  # thang cosine 0-1, như các mode khác
    else:
        raise ValueError(f"search mode không hợp lệ: {mode}")

    if rerank:
        from app.rag.rerank import rerank_rows

        rows = rerank_rows(query, rows)[:top_k]
    else:
        rows = rows[:top_k]

    for r in rows:
        r["display"] = _display(r)
        r["score"] = float(r.get("score") or 0.0)
    return rows


def search_precedents(db: Session, query: str, *, top_k: int = 5) -> list[dict[str, Any]]:
    """Tìm án lệ/bản án gần nhất theo vector (M6b)."""
    n = db.execute(text("SELECT count(*) FROM precedent WHERE embedding IS NOT NULL")).scalar() or 0
    if n == 0:
        return []
    qvec = embed_one(query)
    sql = text(
        """
        SELECT doc_name, court, court_level, precedent_number, is_precedent,
               category, issued_date, source_url, text,
               1 - (embedding <=> CAST(:vec AS vector)) AS score
        FROM precedent
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:vec AS vector)
        LIMIT :k
        """
    )
    rows = [dict(r._mapping) for r in db.execute(sql, {"vec": str(qvec), "k": top_k})]
    for r in rows:
        r["score"] = float(r.get("score") or 0.0)
    return rows
