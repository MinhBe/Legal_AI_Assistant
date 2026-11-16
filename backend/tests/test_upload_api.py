"""Kiểm thử API tải tài liệu lên (upload-ocr-kg-plan, U4)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import app
from app.upload import service

pytestmark = pytest.mark.db

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"
DOCX = "hop-dong-lao-dong-mau.docx"
OCR_JPG = "quyet-dinh-ky-luat-scan.jpg"
TXT = "hoi-dap-noi-bo.txt"
needs_ocr = pytest.mark.skipif(shutil.which("tesseract") is None, reason="thiếu tesseract")


def sample(name: str) -> bytes:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"thiếu mẫu {name}")
    return path.read_bytes()


def _post(client: TestClient, name: str, **extra) -> dict:
    r = client.post("/api/uploads", files={"file": (name, sample(name))}, data=extra)
    assert r.status_code in (200, 202), r.text
    body = r.json()
    if body["status"] == "processing":  # xử lý ở nền xong rồi mới xem trạng thái cuối
        body = client.get(f"/api/uploads/{body['upload_id']}").json()
    return body


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # chạy lifespan: create_all tạo bảng uploaded_file
        yield c


@pytest.fixture
def uploads(client):
    """Dọn mọi tệp do test tạo (node + tệp trên đĩa + row)."""
    made: list[str] = []
    try:
        yield made
    finally:
        for upload_id in made:
            client.delete(f"/api/uploads/{upload_id}")


def test_upload_docx_then_duplicate(client, uploads):
    body = _post(client, DOCX, title="Hợp đồng lao động mẫu")
    uploads.append(body["upload_id"])
    assert body["status"] == "pending_review"
    assert body["n_nodes"] >= 3
    assert body["n_refs"] >= 2
    assert body["data_class"] == "A"
    assert body["duplicate"] is False
    assert body["chars"] > 0
    assert body["preview"]

    again = _post(client, DOCX)
    assert again["upload_id"] == body["upload_id"]
    assert again["duplicate"] is True


@needs_ocr
def test_upload_scanned_jpg_is_ocr(client, uploads):
    body = _post(client, OCR_JPG)
    uploads.append(body["upload_id"])
    assert body["ocr_pages"] == 1
    assert body["mean_ocr_conf"] > 0.6


def test_upload_rejects_unsupported_and_empty(client):
    r = client.post("/api/uploads", files={"file": ("x.exe", b"MZ\x90\x00")})
    assert r.status_code == 415
    assert r.json()["detail"]
    r = client.post("/api/uploads", files={"file": ("rong.txt", b"")})
    assert r.status_code == 422


def test_list_and_approve(client, uploads, db):
    body = _post(client, TXT)
    uploads.append(body["upload_id"])

    ids = {u["upload_id"] for u in client.get("/api/uploads").json()}
    assert body["upload_id"] in ids

    r = client.patch(f"/api/uploads/{body['upload_id']}", json={"status": "approved"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"

    one = client.get(f"/api/uploads/{body['upload_id']}").json()
    assert one["status"] == "approved"
    assert one["reviewed_at"]
    db.rollback()
    doc_status = db.execute(
        text("SELECT status FROM legal_document WHERE doc_id = :d"), {"d": body["doc_id"]}
    ).scalar()
    assert doc_status == "approved"


def test_delete_removes_nodes_and_file(client, uploads, db):
    body = _post(client, TXT)
    uploads.append(body["upload_id"])
    stored = service.UPLOAD_DIR / f"{body['sha256']}.txt"
    assert stored.exists()

    r = client.delete(f"/api/uploads/{body['upload_id']}")
    assert r.status_code == 204
    assert client.get(f"/api/uploads/{body['upload_id']}").status_code == 404
    db.rollback()
    left = db.execute(
        text("SELECT count(*) FROM legal_node WHERE doc_id = :d"), {"d": body["doc_id"]}
    ).scalar()
    assert left == 0
    assert not stored.exists()


@pytest.mark.db
def test_full_text_endpoint_returns_more_than_preview(client):
    """Hồi quy: trang /upload chỉ hiện preview 2000 ký tự nên tài liệu dài trông như bị cắt."""
    data = (SAMPLES / "ban-an-mau-nhieu-trang.pdf").read_bytes()
    r = client.post("/api/uploads", files={"file": ("ban-an-mau-nhieu-trang.pdf", data, "application/pdf")})
    assert r.status_code in (200, 202), r.text
    up = r.json()
    try:
        if up["status"] == "processing":
            up = client.get(f"/api/uploads/{up['upload_id']}").json()
        assert len(up["preview"]) <= 2000
        t = client.get(f"/api/uploads/{up['upload_id']}/text").json()
        assert t["chars"] == len(t["text"]) > 2000
        assert "câu cuối cùng của bản án mẫu nằm ở trang ba." in " ".join(t["text"].split())
    finally:
        client.delete(f"/api/uploads/{up['upload_id']}")


def test_post_returns_processing_or_final_status(client, uploads):
    """Tải lên trả về ngay (202) khi còn xử lý, hoặc trạng thái cuối nếu đã xong."""
    r = client.post("/api/uploads", files={"file": (TXT, sample(TXT))})
    assert r.status_code in (200, 202), r.text
    body = r.json()
    uploads.append(body["upload_id"])
    assert body["status"] in {"processing", "pending_review", "failed"}


def test_reference_to_decree_by_number_creates_node_reference(client, uploads, db):
    """"khoản 1 Điều 3 Nghị định 145/2020/NĐ-CP" phải trỏ tới node của nghị định 145."""
    has_node = db.execute(
        text("SELECT 1 FROM legal_node WHERE node_id = 'nd145_2020-d3-k1'")
    ).scalar()
    if not has_node:
        pytest.skip("kho thiếu nd145_2020-d3-k1")
    content = "Quy định nội bộ: theo khoản 1 Điều 3 Nghị định 145/2020/NĐ-CP.\n".encode()
    r = client.post("/api/uploads", files={"file": ("quy-dinh-noi-bo-u9.txt", content)})
    assert r.status_code in (200, 202), r.text
    up = r.json()
    uploads.append(up["upload_id"])
    if up["status"] == "processing":
        up = client.get(f"/api/uploads/{up['upload_id']}").json()
    assert up["status"] == "pending_review", up.get("error")
    refs = [
        to_id
        for n in client.get(f"/api/uploads/{up['upload_id']}/nodes").json()["nodes"]
        for to_id in n["refs"]
    ]
    assert "nd145_2020-d3-k1" in refs
