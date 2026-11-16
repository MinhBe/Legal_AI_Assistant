"""Dựng knowledge graph (node + cạnh) cho /api/graph.

Một lần dựng có hai pha, và thứ tự là bất biến quan trọng nhất của module:

1. Gom node: kết quả tra cứu, rồi mở rộng ra cha, con, node đối ứng của quan hệ
   thay thế, đích dẫn chiếu, và khép kín cây cha tới tận Điều.
2. Dựng cạnh, rồi thêm tầng Chương và Văn bản (hai tầng này không nằm trong
   bảng legal_node mà được dựng tại chỗ).

Cạnh chỉ nối hai đầu đã có mặt, nên một node thêm SAU pha 1 sẽ mồ côi — không có
cạnh "contains" nào — và bố cục phân cấp ở frontend sẽ văng nó ra xa.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Session

from app.db.models import (
    DocumentRelation,
    LegalDocument,
    LegalNode,
    NodeReference,
    NodeSupersession,
)
from app.rag.search import _display, doc_name, search_nodes

# Điểm → Khoản → Điều là sâu nhất; thêm một vòng phòng dữ liệu lạ
_MAX_ANCESTRY_PASSES = 4
_TEXT_PREVIEW = 300


class _Graph:
    """Tập node + cạnh, chống trùng, chỉ nối hai đầu đã có."""

    def __init__(self, hidden: set[str] | None = None) -> None:
        self.nodes: list[dict[str, Any]] = []
        self.ids: set[str] = set()
        self.edges: list[dict[str, str]] = []
        self.hidden = hidden or set()  # doc_id của văn bản tải lên không được hiện
        self._edge_keys: set[tuple[str, str]] = set()

    def add_node(self, node: dict[str, Any]) -> None:
        if node["id"] in self.ids or node.get("doc_id") in self.hidden:
            return
        self.nodes.append(node)
        self.ids.add(node["id"])

    def add_edge(self, src: str, tgt: str, etype: str) -> None:
        key = (src, tgt)
        if src != tgt and key not in self._edge_keys and src in self.ids and tgt in self.ids:
            self._edge_keys.add(key)
            self.edges.append({"source": src, "target": tgt, "type": etype})


# ── hình dạng node ──────────────────────────────────────────────────────────

def _label(level: str, node_id: str, doc_id: str, heading: str | None, display: str | None) -> str:
    """Node `section` (văn bản tải lên chia đoạn) không có số Điều/Khoản để gọi tên,
    nên dùng tiêu đề đoạn; các mức luật giữ nhãn "Điều … (tên văn bản)"."""
    if level == "section":
        return f"{heading or node_id} ({doc_name(doc_id)})"
    return display or node_id


def _hit_node(h: dict[str, Any]) -> dict[str, Any]:
    level = h.get("level") or "article"
    return {
        "id": h["node_id"],
        "label": _label(level, h["node_id"], h["doc_id"], h.get("heading"), h.get("display")),
        "doc_id": h["doc_id"],
        "level": level,
        "type": level,
        "heading": h.get("heading", ""),
        "text": (h.get("text") or "")[:_TEXT_PREVIEW],
        "score": round(h.get("score", 0.0), 3),
    }


def _orm_node(n: LegalNode, *, ghost: bool) -> dict[str, Any]:
    label = _display({
        "node_id": n.node_id, "doc_id": n.doc_id,
        "article_no": n.article_no, "clause_no": n.clause_no, "point_letter": n.point_letter,
    })
    return {
        "id": n.node_id,
        "label": _label(n.level, n.node_id, n.doc_id, n.heading, label),
        "doc_id": n.doc_id,
        "level": n.level, "type": n.level, "heading": n.heading or "",
        "text": (n.text or "")[:_TEXT_PREVIEW], "score": 0.0, "ghost": ghost,
    }


def _load_nodes(db: Session, g: _Graph, ids: set[str], *, ghost: bool) -> None:
    if ids:
        for obj in db.execute(select(LegalNode).where(LegalNode.node_id.in_(list(ids)))).scalars():
            g.add_node(_orm_node(obj, ghost=ghost))


# ── pha 1: gom node ─────────────────────────────────────────────────────────

def _upload_exclusion(include_uploads: bool) -> str:
    """Mảnh SQL loại văn bản tải lên, y như search_nodes (chưa duyệt thì không bao giờ)."""
    if include_uploads:
        return (
            " AND doc_id NOT IN (SELECT doc_id FROM legal_document"
            " WHERE doc_type = 'upload' AND status IS DISTINCT FROM 'approved')"
        )
    return " AND doc_id NOT IN (SELECT doc_id FROM legal_document WHERE doc_type = 'upload')"


def _seed_hits(
    db: Session,
    query: str,
    top_k: int,
    *,
    doc_id: str | None = None,
    include_uploads: bool = False,
) -> list[dict[str, Any]]:
    """Có doc_id: lấy node của văn bản đó theo thứ tự. Có từ khoá: tìm theo nội dung.
    Không có: lấy Điều trước, rồi Khoản, rồi Điểm."""
    if doc_id:
        hits = []
        for n in db.execute(
            select(LegalNode)
            .where(LegalNode.doc_id == doc_id)
            .order_by(LegalNode.seq, LegalNode.node_id)
            .limit(top_k)
        ).scalars():
            h = {
                "node_id": n.node_id, "doc_id": n.doc_id, "level": n.level,
                "article_no": n.article_no, "clause_no": n.clause_no,
                "point_letter": n.point_letter, "heading": n.heading, "text": n.text,
            }
            h["display"] = _display(h)
            h["score"] = 0.0
            hits.append(h)
        return hits
    if query.strip():
        return search_nodes(db, query, top_k=top_k, include_uploads=include_uploads)
    rows = db.execute(
        sa_text(
            "SELECT node_id, doc_id, article_no, clause_no, point_letter, heading, text, level, parent_id "
            "FROM legal_node WHERE 1 = 1 "
            + _upload_exclusion(include_uploads)
            + " ORDER BY CASE level WHEN 'article' THEN 0 WHEN 'clause' THEN 1 ELSE 2 END, node_id "
            "LIMIT :k"
        ),
        {"k": top_k},
    ).all()
    hits = []
    for r in rows:
        d = dict(r._mapping)
        d["display"] = _display(d)
        d["score"] = 0.0
        hits.append(d)
    return hits


def _add_missing_parents(db: Session, g: _Graph) -> None:
    pairs = db.execute(
        select(LegalNode.node_id, LegalNode.parent_id)
        .where(LegalNode.node_id.in_(list(g.ids)))
        .where(LegalNode.parent_id.isnot(None))
    ).all()
    _load_nodes(db, g, {pid for _, pid in pairs if pid not in g.ids}, ghost=False)


def _add_article_children(db: Session, g: _Graph) -> None:
    """Mỗi Điều hiện đủ Khoản của nó, để cạnh Điều–Khoản không bị đứt."""
    article_ids = [n["id"] for n in g.nodes if n["level"] == "article"]
    if not article_ids:
        return
    for obj in db.execute(
        select(LegalNode)
        .where(LegalNode.parent_id.in_(article_ids))
        .where(~LegalNode.node_id.in_(list(g.ids)))
    ).scalars():
        g.add_node(_orm_node(obj, ghost=False))


def _add_supersession_nodes(db: Session, g: _Graph) -> list[tuple[str, str, str | None]]:
    rows = db.execute(
        select(NodeSupersession.old_id, NodeSupersession.new_id, NodeSupersession.change_type).where(
            NodeSupersession.old_id.in_(list(g.ids)) | NodeSupersession.new_id.in_(list(g.ids))
        )
    ).all()
    _load_nodes(db, g, {nid for old, new, _ in rows for nid in (old, new) if nid not in g.ids}, ghost=True)
    return [tuple(r) for r in rows]


def _add_reference_targets(db: Session, g: _Graph) -> None:
    """Dẫn chiếu là cạnh duy nhất cắt ngang cây, nên gần như luôn trỏ ra ngoài
    lát cắt top_k. Không kéo đích vào thì mạng dẫn chiếu coi như vô hình."""
    pairs = db.execute(
        select(NodeReference.from_id, NodeReference.to_id).where(
            NodeReference.from_id.in_(list(g.ids)) | NodeReference.to_id.in_(list(g.ids))
        )
    ).all()
    _load_nodes(db, g, {nid for pair in pairs for nid in pair if nid not in g.ids}, ghost=True)


def _close_ancestry(db: Session, g: _Graph) -> None:
    """Mọi node đều phải lần được về Điều của nó, kể cả node vừa kéo vào."""
    for _ in range(_MAX_ANCESTRY_PASSES):
        missing = set(db.execute(
            select(LegalNode.parent_id)
            .where(LegalNode.node_id.in_(list(g.ids)))
            .where(LegalNode.parent_id.isnot(None))
            .where(~LegalNode.parent_id.in_(list(g.ids)))
        ).scalars())
        if not missing:
            return
        _load_nodes(db, g, missing, ghost=True)


# ── pha 2: cạnh, rồi tầng Chương và Văn bản ─────────────────────────────────

def _add_tree_edges(db: Session, g: _Graph, legal_ids: list[str]) -> dict[str, list[str]]:
    """Cha → con ("contains"), và các con liền kề cùng cha ("sibling")."""
    pairs = db.execute(
        select(LegalNode.node_id, LegalNode.parent_id)
        .where(LegalNode.node_id.in_(legal_ids))
        .where(LegalNode.parent_id.isnot(None))
    ).all()
    children: dict[str, list[str]] = {}
    for nid, pid in pairs:
        g.add_edge(pid, nid, "contains")
        children.setdefault(pid, []).append(nid)
    return children


def _add_sibling_edges(g: _Graph, children: dict[str, list[str]]) -> None:
    for kids in children.values():
        kids.sort()
        for a, b in zip(kids, kids[1:], strict=False):
            g.add_edge(a, b, "sibling")


def _add_reference_edges(db: Session, g: _Graph, legal_ids: list[str]) -> None:
    for f_id, t_id in db.execute(
        select(NodeReference.from_id, NodeReference.to_id)
        .where(NodeReference.from_id.in_(legal_ids))
        .where(NodeReference.to_id.in_(legal_ids))
    ).all():
        g.add_edge(f_id, t_id, "references")


def _add_chapters(db: Session, g: _Graph, legal_ids: list[str]) -> None:
    """Tầng Chương nằm trong cột chapter_no / chapter_title (scripts/backfill_chapters.py)."""
    chap_of: dict[str, tuple[str, int, str]] = {}
    for nid, d_id, ch_no, ch_title in db.execute(
        select(LegalNode.node_id, LegalNode.doc_id, LegalNode.chapter_no, LegalNode.chapter_title)
        .where(LegalNode.node_id.in_(legal_ids))
    ).all():
        if ch_no is not None:
            chap_of[nid] = (d_id, ch_no, ch_title or "")

    for n in g.nodes:
        if info := chap_of.get(n["id"]):
            n["chapter_no"], n["chapter_title"] = info[1], info[2]

    for d_id, ch_no, ch_title in chap_of.values():
        g.add_node({
            "id": f"chap:{d_id}:{ch_no}", "label": f"Chương {ch_no}", "doc_id": d_id,
            "level": "chapter", "type": "chapter",
            "chapter_no": ch_no, "chapter_title": ch_title,
            "heading": ch_title or f"Chương {ch_no}",
            "text": ch_title or "", "score": 0.0, "ghost": False,
        })

    for n in g.nodes:
        if n.get("type") == "article" and n.get("chapter_no") is not None:
            g.add_edge(f"chap:{n['doc_id']}:{n['chapter_no']}", n["id"], "contains")


def _add_documents(db: Session, g: _Graph) -> dict[str, str]:
    """Node Văn bản, cạnh Văn bản → Chương (hoặc → Điều chưa có Chương), và
    quan hệ giữa các văn bản. Trả về doc_id → doc_type để gom cụm."""
    doc_ids = sorted({n["doc_id"] for n in g.nodes if n.get("doc_id")})
    if not doc_ids:
        return {}
    docs = db.execute(select(LegalDocument).where(LegalDocument.doc_id.in_(doc_ids))).scalars().all()
    for d in docs:
        g.add_node({
            "id": f"doc:{d.doc_id}", "label": doc_name(d.doc_id), "doc_id": d.doc_id,
            "level": "document", "type": "document", "doc_type": d.doc_type or "",
            "heading": d.title or d.doc_id, "text": d.title or "", "score": 0.0, "ghost": False,
        })

    for n in g.nodes:
        if n.get("type") in ("chapter", "section") or (
            n.get("type") == "article" and n.get("chapter_no") is None
        ):
            g.add_edge(f"doc:{n['doc_id']}", n["id"], "contains")

    for f_doc, t_doc, rel in db.execute(
        select(DocumentRelation.from_doc, DocumentRelation.to_doc, DocumentRelation.rel)
        .where(DocumentRelation.from_doc.in_(doc_ids))
        .where(DocumentRelation.to_doc.in_(doc_ids))
    ).all():
        g.add_edge(f"doc:{f_doc}", f"doc:{t_doc}", (rel or "related").lower())

    return {d.doc_id: (d.doc_type or "", d.status or "") for d in docs}


# ── điểm vào ────────────────────────────────────────────────────────────────

def _hidden_docs(db: Session, doc_id: str | None, include_uploads: bool) -> set[str]:
    """Văn bản tải lên chưa duyệt không được hiện — kể cả khi chúng dẫn chiếu tới
    node luật đang có trong đồ thị (pha 1 kéo ngược từ node đích về nguồn)."""
    rows = db.execute(
        select(LegalDocument.doc_id, LegalDocument.status)
        .where(LegalDocument.doc_type == "upload")
    ).all()
    return {
        d for d, status in rows
        if d != doc_id and not (include_uploads and status == "approved")
    }


def build_graph(
    db: Session,
    query: str,
    top_k: int,
    *,
    doc_id: str | None = None,
    include_uploads: bool = False,
) -> dict[str, Any]:
    hits = _seed_hits(db, query, top_k, doc_id=doc_id, include_uploads=include_uploads)
    if not hits:
        return {"nodes": [], "edges": [], "query": query}

    g = _Graph(_hidden_docs(db, doc_id, include_uploads))
    for h in hits:
        g.add_node(_hit_node(h))

    # pha 1 — gom đủ node trước khi dựng bất kỳ cạnh nào
    _add_missing_parents(db, g)
    _add_article_children(db, g)
    supersessions = _add_supersession_nodes(db, g)
    _add_reference_targets(db, g)
    _close_ancestry(db, g)

    # pha 2
    legal_ids = [n["id"] for n in g.nodes]
    children = _add_tree_edges(db, g, legal_ids)
    for old_id, new_id, change_type in supersessions:
        g.add_edge(old_id, new_id, change_type or "superseded_by")
    _add_reference_edges(db, g, legal_ids)
    _add_sibling_edges(g, children)
    _add_chapters(db, g, legal_ids)
    doc_type = _add_documents(db, g)

    for n in g.nodes:
        dtype, status = doc_type.get(n.get("doc_id", ""), ("", ""))
        n["doc_type"] = dtype
        n["upload"] = dtype == "upload"
        n["doc_name"] = doc_name(n.get("doc_id", ""))
        if n["upload"] and n.get("type") == "document":
            n["status"] = status

    return {"nodes": g.nodes, "edges": g.edges, "query": query}
