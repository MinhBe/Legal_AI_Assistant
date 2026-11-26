"""Công cụ MCP chỉ-đọc trên kho Legal Agentic.

Mỗi hàm nhận một Session và trả dict/list thuần JSON, không ghi DB, không gọi LLM.
Module nghiệp vụ được nạp trễ (qua `_mod`) để import nhẹ và để test thay được bằng giả.
"""

from __future__ import annotations

import importlib
from datetime import date
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

MAX_TOP_K = 20
MAX_TEXT = 1500


def _mod(name: str):
    return importlib.import_module(name)


def _day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"Ngày phải dạng YYYY-MM-DD, nhận được: {value!r}") from exc


def _k(top_k: int) -> int:
    return max(1, min(int(top_k), MAX_TOP_K))


def _iso(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _clip(text: str | None) -> str:
    text = text or ""
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT] + "…"


def search_law(
    db: Session,
    query: str,
    as_of: str | None = None,
    top_k: int = 5,
    domains: list[str] | None = None,
) -> dict[str, Any]:
    """Tìm điều/khoản luật còn hiệu lực tại `as_of` (mặc định: hôm nay)."""
    if not query.strip():
        raise ValueError("Câu hỏi trống")
    day = _day(as_of) or date.today()
    search = _mod("app.rag.search")
    rows = search.search_nodes(db, query, top_k=_k(top_k), as_of=day, domains=domains)
    return {
        "as_of": day.isoformat(),
        "results": [
            {
                "node_id": r.get("node_id"),
                "doc_id": r.get("doc_id"),
                "doc_name": search.doc_name(r.get("doc_id") or ""),
                "citation": r.get("display"),
                "article_no": r.get("article_no"),
                "clause_no": r.get("clause_no"),
                "point_letter": r.get("point_letter"),
                "heading": r.get("heading"),
                "text": _clip(r.get("text")),
                "score": round(float(r.get("score") or 0.0), 4),
            }
            for r in rows
        ],
    }


def get_article(
    db: Session, doc_id: str, article_no: str, clause_no: str | None = None
) -> dict[str, Any]:
    """Toàn văn một điều (hoặc một khoản) kèm mốc hiệu lực của từng node."""
    models = _mod("app.db.models")
    node = models.LegalNode
    stmt = select(node).where(node.doc_id == doc_id, node.article_no == str(article_no))
    if clause_no:
        stmt = stmt.where(node.clause_no == str(clause_no))
    rows = list(db.scalars(stmt.order_by(node.node_id)).all())
    return {
        "doc_id": doc_id,
        "article_no": str(article_no),
        "clause_no": clause_no,
        "found": bool(rows),
        "nodes": [
            {
                "node_id": n.node_id,
                "level": n.level,
                "clause_no": n.clause_no,
                "point_letter": n.point_letter,
                "heading": n.heading,
                "text": n.text,
                "effective_from": _iso(n.effective_from),
                "effective_to": _iso(n.effective_to),
            }
            for n in rows
        ],
    }


def law_versions(db: Session, provision_key: str) -> dict[str, Any]:
    """Lịch sử các phiên bản của một điều khoản (thời điểm áp dụng, nguồn)."""
    versions = _mod("app.amend.versions").versions_for(db, provision_key)
    return {
        "provision_key": provision_key,
        "versions": [{k: _iso(v) for k, v in row.items()} for row in versions],
    }


def in_force(db: Session, day: str, doc_id: str | None = None) -> dict[str, Any]:
    """Các điều khoản còn hiệu lực tại một ngày (lọc theo văn bản nếu có)."""
    d = _day(day)
    if d is None:
        raise ValueError("Cần ngày dạng YYYY-MM-DD")
    keys = _mod("app.amend.versions").in_force_at(db, d, doc_id=doc_id)
    return {"day": d.isoformat(), "doc_id": doc_id, "count": len(keys), "provision_keys": keys[:500]}


def document_relations(db: Session, doc_id: str) -> dict[str, Any]:
    """Văn bản này sửa đổi/thay thế/hướng dẫn văn bản nào, và bị văn bản nào tác động."""
    models = _mod("app.db.models")
    rel = models.DocumentRelation
    rows = db.scalars(select(rel).where(or_(rel.from_doc == doc_id, rel.to_doc == doc_id))).all()
    doc = db.get(models.LegalDocument, doc_id)
    return {
        "doc_id": doc_id,
        "document": None
        if doc is None
        else {
            "title": doc.title,
            "number": doc.number,
            "status": doc.status,
            "issued_date": _iso(doc.issued_date),
            "effective_date": _iso(doc.effective_date),
            "expired_date": _iso(doc.expired_date),
            "source_url": doc.source_url,
        },
        "outgoing": [{"rel": r.rel, "to_doc": r.to_doc} for r in rows if r.from_doc == doc_id],
        "incoming": [{"rel": r.rel, "from_doc": r.from_doc} for r in rows if r.to_doc == doc_id],
    }


def corpus_freshness(db: Session, topic: str = "") -> dict[str, Any]:
    """Kho luật nạp lần cuối khi nào, có quá hạn cập nhật cho chủ đề này không."""
    out = _mod("app.amend.cascade").corpus_freshness(db, date.today(), topic_hint=topic)
    return {k: _iso(v) for k, v in out.items()}


def search_precedents(db: Session, query: str, top_k: int = 5) -> dict[str, Any]:
    """Án lệ/bản án gần nhất về nghĩa với tình huống."""
    if not query.strip():
        raise ValueError("Câu hỏi trống")
    rows = _mod("app.rag.search").search_precedents(db, query, top_k=_k(top_k))
    return {
        "results": [
            {
                "doc_name": r.get("doc_name"),
                "court": r.get("court"),
                "court_level": r.get("court_level"),
                "precedent_number": r.get("precedent_number"),
                "is_precedent": r.get("is_precedent"),
                "category": r.get("category"),
                "issued_date": _iso(r.get("issued_date")),
                "source_url": r.get("source_url"),
                "excerpt": _clip(r.get("text")),
                "score": round(float(r.get("score") or 0.0), 4),
            }
            for r in rows
        ]
    }


def recent_updates(db: Session, limit: int = 10, labor_only: bool = False) -> dict[str, Any]:
    """Tin văn bản pháp luật mới quét được (Công báo, vbpl...), mới nhất trước."""
    store = _mod("app.intel.store")
    rows = store.items(db, labor=True if labor_only else None, limit=_k(limit))
    keep = ("id", "source", "url", "title", "number", "kind", "category", "listed_date",
            "labor_hint", "in_corpus", "priority", "status")
    numbers = _mod("app.intel.watchlist").corpus_numbers(db)
    out = []
    for it in rows:
        full = store.item_dict(db, it, numbers)
        out.append({k: full.get(k) for k in keep})
    return {"items": out}
