"""Tệp tải lên -> node đồ thị (upload-ocr-kg-plan, U3).

Nhận cấu trúc Điều/Khoản/Điểm thì dùng lại parser luật; văn bản tự do (hợp đồng,
nội quy, công văn) thì chia đoạn thành node `section`. Không gọi mạng, không gọi LLM.
Dữ liệu tải lên là mức A: `doc_type='upload'`, `status='pending_review'`, mặc định
bị loại khỏi truy xuất chat cho tới khi được duyệt.
"""

from __future__ import annotations

import hashlib
import re

from sqlalchemy import delete, text as sql_text
from sqlalchemy.orm import Session

from app.db.models import LegalDocument, LegalNode, NodeReference
from app.ingestion.ingest import _nodes_from_articles
from app.ingestion.parser import assign_ids, parse_articles, validate
from app.ingestion.references import extract_refs
from app.rag.embeddings import embed

SECTION_TARGET = 800  # ký tự mỗi node section
SECTION_MAX = 1200  # đoạn dài hơn ngần này thì cắt tại cuối câu


def make_doc_id(sha256_hex: str) -> str:
    return "up_" + sha256_hex[:10]


def _split_long(para: str) -> list[str]:
    """Cắt đoạn dài tại ". ", "; " hoặc xuống dòng, không mất chữ."""
    out: list[str] = []
    while len(para) > SECTION_MAX:
        window = para[: SECTION_MAX + 1]
        idx = max(window.rfind(". "), window.rfind("; "), window.rfind("\n"))
        cut = idx + 1 if idx > 0 else SECTION_MAX
        out.append(para[:cut].strip())
        para = para[cut:].strip()
    if para:
        out.append(para)
    return out


def split_sections(text: str) -> list[str]:
    """Đoạn (cách nhau dòng trống) gộp dần tới SECTION_TARGET ký tự."""
    chunks: list[str] = []
    cur = ""
    for para in re.split(r"\n\s*\n", text):
        for piece in _split_long(para.strip()):
            if not cur:
                cur = piece
            elif len(cur) + len(piece) + 2 <= SECTION_TARGET:
                cur += "\n\n" + piece
            else:
                chunks.append(cur)
                cur = piece
    if cur:
        chunks.append(cur)
    return chunks


def build_rows(doc_id: str, title: str, text: str) -> tuple[str, list[dict]]:
    if not text or not text.strip():
        raise ValueError("no text")

    articles = parse_articles(text)
    assign_ids(doc_id, articles)
    if len(articles) >= 1 and not validate(articles, text):
        return "articles", _nodes_from_articles(doc_id, articles, None, None)

    rows = []
    for i, chunk in enumerate(split_sections(text), 1):
        rows.append(
            dict(
                node_id=f"{doc_id}-s{i}", doc_id=doc_id, level="section",
                article_no=None, clause_no=None, point_letter=None, parent_id=None,
                heading=chunk.split("\n")[0][:80], text=chunk, seq=i,
                _ctx=f"{title}: {chunk}",
            )
        )
    return "sections", rows


def _hash(text_: str) -> str:
    return hashlib.sha256(text_.encode("utf-8")).hexdigest()[:16]


def delete_upload(db: Session, doc_id: str) -> None:
    """Xoá văn bản tải lên; node và dẫn chiếu xoá theo khoá ngoại CASCADE."""
    db.execute(delete(LegalDocument).where(LegalDocument.doc_id == doc_id))


def ingest_upload(
    db: Session, *, doc_id: str, title: str, text: str, filename: str
) -> dict:
    mode, rows = build_rows(doc_id, title, text)
    delete_upload(db, doc_id)
    db.add(
        LegalDocument(
            doc_id=doc_id, title=title, doc_type="upload",
            status="pending_review", source_url=f"upload://{filename}",
        )
    )
    vecs = embed([r["_ctx"] for r in rows])
    for r, v in zip(rows, vecs, strict=True):
        r.pop("_ctx")
        db.add(LegalNode(**r, text_hash=_hash(r["text"]), embedding=v))
    db.flush()

    article_text = {r["article_no"]: r["text"] for r in rows if r["level"] == "article"}
    pairs: dict[tuple[str, str], str] = {}
    for r in rows:
        ctx = None if r["level"] == "section" else article_text.get(r["article_no"])
        for to_id, ref_text in extract_refs(r["text"], doc_id, article_context=ctx):
            if to_id != r["node_id"]:
                pairs.setdefault((r["node_id"], to_id), ref_text)

    existing: set[str] = set()
    if pairs:
        targets = sorted({t for _, t in pairs})
        existing = {
            row[0]
            for row in db.execute(
                sql_text("SELECT node_id FROM legal_node WHERE node_id = ANY(:ids)"),
                {"ids": targets},
            )
        }
    for (from_id, to_id), ref_text in pairs.items():
        if to_id in existing:
            db.add(NodeReference(from_id=from_id, to_id=to_id, ref_text=ref_text))
    db.commit()

    ref_targets = sorted({to_id for _, to_id in pairs if to_id in existing})
    return {
        "doc_id": doc_id, "parse_mode": mode, "n_nodes": len(rows),
        "n_refs": sum(1 for _, to_id in pairs if to_id in existing),
        "ref_targets": ref_targets,
    }
