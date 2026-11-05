"""search_nodes trên DB thật, cả 3 chế độ (V2). Trước commit này chỉ `vector` có test
chạy trên DB; `bm25`/`hybrid` chỉ được kiểm bằng cách chạy tay scripts/eval_gold.py."""

import pytest

from app.rag.search import search_nodes

pytestmark = pytest.mark.db


def test_vector_mode_finds_the_probation_article(db):
    hits = search_nodes(db, "Thời gian thử việc tối đa là bao lâu?", top_k=8, mode="vector")
    assert hits and any(h["node_id"].startswith("blld2019-d25") for h in hits)


def test_bm25_mode_finds_the_probation_article(db):
    hits = search_nodes(db, "Thời gian thử việc tối đa là bao lâu?", top_k=8, mode="bm25")
    assert hits and any(h["node_id"].startswith("blld2019-d25") for h in hits)
    assert all("score" in h for h in hits)


def test_hybrid_mode_finds_the_probation_article(db):
    hits = search_nodes(db, "Thời gian thử việc tối đa là bao lâu?", top_k=8, mode="hybrid")
    assert hits and any(h["node_id"].startswith("blld2019-d25") for h in hits)
    # score hiển thị phải ở thang cosine 0-1 như các mode khác (xem app/rag/search.py)
    assert all(0.0 <= h["score"] <= 1.0 for h in hits)


def test_unknown_mode_raises_on_db(db):
    with pytest.raises(ValueError, match="mode"):
        search_nodes(db, "bất kỳ câu gì", top_k=8, mode="khong_ton_tai")


def test_rerank_keeps_or_improves_the_top1_or_falls_back_safely(db):
    """Rerank không bao giờ được làm hỏng câu trả lời (app/rag/rerank.py): lỗi thì giữ
    nguyên thứ tự cũ. Ở đây chỉ kiểm nó chạy được và vẫn trả đủ top_k kết quả."""
    hits = search_nodes(db, "Thời gian thử việc tối đa là bao lâu?", top_k=5, mode="vector", rerank=True)
    assert len(hits) == 5
    assert any(h["node_id"].startswith("blld2019-d25") for h in hits)
