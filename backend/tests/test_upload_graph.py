"""Đồ thị của một văn bản tải lên (upload-ocr-kg-plan, U5).

Văn bản tải lên nằm ngoài cây luật, nên chỉ vào đồ thị khi được gọi đích danh bằng
`doc_id`; đồ thị tra cứu thường ngày vẫn phải ẩn nó.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.graph.builder import build_graph
from app.main import app
from app.upload import service

pytestmark = pytest.mark.db

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"
PDF = "noi-quy-lao-dong.pdf"
DOCX = "hop-dong-lao-dong-mau.docx"
TXT = "hoi-dap-noi-bo.txt"


def sample(name: str) -> bytes:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"thiếu mẫu {name}")
    return path.read_bytes()


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # chạy lifespan: create_all tạo bảng uploaded_file
        yield c


@pytest.fixture
def uploaded(db, request):
    """Tệp mẫu đã nạp; dọn node + tệp + row sau mỗi test."""
    row = service.save_upload(db, sample(request.param), request.param)
    try:
        yield row
    finally:
        service.remove_upload(db, row.upload_id)


def _reachable(edges, root: str) -> set[str]:
    kids: dict[str, list[str]] = {}
    for e in edges:
        if e["type"] == "contains":
            kids.setdefault(e["source"], []).append(e["target"])
    seen = {root}
    stack = [root]
    while stack:
        for kid in kids.get(stack.pop(), []):
            if kid not in seen:
                seen.add(kid)
                stack.append(kid)
    return seen


@pytest.mark.parametrize("uploaded", [PDF], indirect=True)
def test_pdf_graph_hangs_off_document_and_reaches_the_law(db, uploaded):
    doc_id = uploaded.doc_id
    g = build_graph(db, "", 150, doc_id=doc_id)
    by_id = {n["id"]: n for n in g["nodes"]}

    root = by_id[f"doc:{doc_id}"]
    assert root["upload"] is True
    assert root["status"] == "pending_review"
    assert "blld2019-d125" in by_id

    upload_ids = {n["id"] for n in g["nodes"] if n["upload"] and n["type"] != "document"}
    assert upload_ids
    assert upload_ids <= _reachable(g["edges"], f"doc:{doc_id}")

    refs = [
        e for e in g["edges"]
        if e["type"] == "references" and by_id[e["source"]]["upload"]
        and by_id[e["target"]]["doc_id"] == "blld2019"
    ]
    assert refs


@pytest.mark.parametrize("uploaded", [DOCX], indirect=True)
def test_docx_graph_nodes_are_contained_and_labelled(db, uploaded):
    doc_id = uploaded.doc_id
    g = build_graph(db, "", 150, doc_id=doc_id)
    by_id = {n["id"]: n for n in g["nodes"]}

    upload_ids = {n["id"] for n in g["nodes"] if n["upload"] and n["type"] != "document"}
    assert upload_ids
    assert upload_ids <= _reachable(g["edges"], f"doc:{doc_id}")
    assert [by_id[i]["label"] for i in upload_ids if by_id[i]["label"].startswith("up_")] == []

    # mẫu này tách được Điều/Khoản; nếu parser từ chối thì rơi về node section
    for n in g["nodes"]:
        if n["level"] == "section":
            assert not n["label"].startswith("up_")
            assert {"source": f"doc:{doc_id}", "target": n["id"], "type": "contains"} in g["edges"]


@pytest.mark.parametrize("uploaded", [TXT], indirect=True)
def test_section_nodes_take_heading_and_hang_off_document(db, uploaded):
    doc_id = uploaded.doc_id
    g = build_graph(db, "", 150, doc_id=doc_id)
    sections = [n for n in g["nodes"] if n["level"] == "section"]
    assert sections
    for n in sections:
        assert not n["label"].startswith("up_")
        assert n["label"].startswith(n["heading"])
        assert {"source": f"doc:{doc_id}", "target": n["id"], "type": "contains"} in g["edges"]


@pytest.mark.parametrize("uploaded", [PDF], indirect=True)
def test_query_graph_hides_uploads(db, uploaded):
    g = build_graph(db, "kỷ luật sa thải", 150)
    assert [n["id"] for n in g["nodes"] if n["upload"]] == []


@pytest.mark.parametrize("uploaded", [PDF], indirect=True)
def test_api_graph_doc_id_matches_builder(db, client, uploaded):
    direct = build_graph(db, "", 150, doc_id=uploaded.doc_id)
    r = client.get("/api/graph", params={"doc_id": uploaded.doc_id, "top_k": 150})
    assert r.status_code == 200, r.text
    assert {n["id"] for n in r.json()["nodes"]} == {n["id"] for n in direct["nodes"]}
