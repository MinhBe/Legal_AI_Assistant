"""Gold set phải đúng định dạng và mọi mã điều luật phải tồn tại trong kho."""

import json
from collections import Counter
from pathlib import Path

import pytest

GOLD = Path(__file__).resolve().parents[1] / "eval" / "gold_v1.jsonl"
WANT = {"tra_cuu": 25, "nghi_dinh": 5, "thoi_diem": 5, "nhieu_van_de": 5, "ngoai_kho": 5, "noi_tiep": 5}


def _rows():
    return [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_gold_shape():
    rows = _rows()
    assert len(rows) == 50
    assert len({r["id"] for r in rows}) == 50
    assert Counter(r["category"] for r in rows) == WANT
    for r in rows:
        assert r["expect"] in ("answer", "refuse")
        assert (r["expect"] == "refuse") == (r["category"] == "ngoai_kho")
        if r["expect"] == "answer":
            assert r["expected_articles"], r["id"]
        if r["category"] == "thoi_diem":
            assert r["as_of"] and r["expected_articles_as_of"], r["id"]
        if r["category"] == "noi_tiep":
            assert r["history"], r["id"]
        if r["category"] == "nhieu_van_de":
            assert len(r["question"].split()) >= 60, f"{r['id']}: tình huống phải dài ít nhất 60 từ"
            assert len(r["expected_articles"]) >= 2, f"{r['id']}: phải có ít nhất 2 Điều đúng"


@pytest.mark.db
def test_gold_ids_exist(db):
    from sqlalchemy import text
    ids = set(db.execute(text("SELECT node_id FROM legal_node")).scalars())
    for r in _rows():
        for a in r["expected_articles"] + (r["expected_articles_as_of"] or []) + r["expected_nodes"]:
            assert a in ids, f"{r['id']}: {a} không có trong kho"
