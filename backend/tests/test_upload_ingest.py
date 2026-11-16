"""Kiểm thử nạp tệp tải lên thành node đồ thị (upload-ocr-kg-plan, U3)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from sqlalchemy import text

from app.rag.search import search_nodes
from app.upload import ingest as ig
from app.upload.extract import extract

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"
PDF = "noi-quy-lao-dong.pdf"
DOCX = "hop-dong-lao-dong-mau.docx"


def sample(name: str) -> bytes:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"thiếu mẫu {name}")
    return path.read_bytes()


def flat(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def test_make_doc_id():
    assert ig.make_doc_id("ab" * 32) == "up_ababababab"
    assert ig.make_doc_id("0123456789abcdef") == "up_0123456789"


def test_split_sections_merges_short_paragraphs():
    text = "\n\n".join(["x" * 200] * 30)
    chunks = ig.split_sections(text)
    assert len(chunks) < 30
    assert all(len(c) <= ig.SECTION_MAX for c in chunks)
    assert flat(" ".join(chunks)) == flat(text)


def test_split_sections_cuts_long_paragraph_at_sentence_end():
    para = ("Câu một hai ba bốn năm sáu bảy tám chín mười. " * 60).strip()
    chunks = ig.split_sections(para)
    assert len(chunks) > 1
    assert all(len(c) <= ig.SECTION_MAX for c in chunks)
    assert flat(" ".join(chunks)) == flat(para)


def test_build_rows_pdf_keeps_article_structure():
    e = extract(sample(PDF), PDF)
    mode, rows = ig.build_rows("up_x", "Nội quy lao động Công ty Mẫu An Bình", e.text)
    assert mode == "articles"
    assert "up_x-d3" in {r["node_id"] for r in rows}
    assert all(r["_ctx"] for r in rows)


def test_build_rows_docx_has_unique_ids():
    e = extract(sample(DOCX), DOCX)
    mode, rows = ig.build_rows("up_y", "Hợp đồng lao động mẫu", e.text)
    assert mode in {"articles", "sections"}
    ids = [r["node_id"] for r in rows]
    assert len(rows) >= 3
    assert len(set(ids)) == len(ids)


def test_build_rows_rejects_empty_text():
    with pytest.raises(ValueError, match="no text"):
        ig.build_rows("up_empty", "Trống", "   \n\n ")


@pytest.mark.db
def test_ingest_upload_writes_nodes_refs_and_hides_from_search(db):
    doc_id = "up_testu3pdf"
    e = extract(sample(PDF), PDF)
    try:
        res = ig.ingest_upload(
            db, doc_id=doc_id, title="Nội quy lao động Công ty Mẫu An Bình",
            text=e.text, filename=PDF,
        )
        assert res["parse_mode"] == "articles"
        assert res["n_nodes"] > 0
        assert res["n_refs"] >= 3
        assert "blld2019-d125" in res["ref_targets"]

        hits = search_nodes(db, "sa thải nội quy Công ty Mẫu An Bình", top_k=20)
        assert not [h for h in hits if h["doc_id"].startswith("up_")]

        db.execute(
            text("UPDATE legal_document SET status = 'approved' WHERE doc_id = :d"),
            {"d": doc_id},
        )
        db.commit()
        search_nodes(
            db, "sa thải nội quy Công ty Mẫu An Bình", top_k=20, include_uploads=True
        )
    finally:
        ig.delete_upload(db, doc_id)
        db.commit()
        left = db.execute(
            text("SELECT count(*) FROM legal_document WHERE doc_id = :d"), {"d": doc_id}
        ).scalar()
        assert left == 0
