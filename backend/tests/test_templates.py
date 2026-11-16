"""Biểu mẫu (TPL1): tải lên, tìm kiếm, quyền và việc biểu mẫu không lọt vào kho luật.

Cả tệp chạy với AUTH_REQUIRED=true (conftest tắt cho mọi tệp khác).
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.templates_lib import service as tpl

pytestmark = pytest.mark.db


@pytest.fixture(autouse=True)
def _auth_on(_auth_mode, monkeypatch):
    from app.auth import deps

    monkeypatch.setattr(deps.settings, "auth_required", True)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # chạy lifespan: create_all tạo bảng template
        yield c


def login(client: TestClient, username: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"username": username, "password": username})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(scope="module")
def admin(client):
    return login(client, "admin")


@pytest.fixture(scope="module")
def user1(client):
    return login(client, "user1")


@pytest.fixture
def made(client, admin):
    """Xoá hẳn biểu mẫu và tệp do test tạo."""
    ids: list[str] = []
    yield ids
    for template_id in ids:
        client.delete(f"/api/templates/{template_id}?hard=true", headers=admin)


def docx_bytes(*lines: str) -> bytes:
    import docx

    document = docx.Document()
    for line in lines:
        document.add_paragraph(line)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def upload(client, headers, data: bytes, name: str, kind: str, **extra):
    return client.post(
        "/api/templates",
        headers=headers,
        files={
            "file": (
                f"{name}.docx",
                data,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
        data={"name": name, "kind": kind, **extra},
    )


def test_upload_docx_detects_placeholders_and_duplicate(client, admin, made):
    data = docx_bytes("Họ và tên: ……", "Công ty: {{ten_cong_ty}}", "Chức danh: [chuc_danh]")
    resp = upload(client, admin, data, "Hợp đồng thử nghiệm", "hop_dong")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    made.append(body["id"])
    assert body["kind"] == "hop_dong" and body["version"] == 1
    assert "{{ten_cong_ty}}" in body["placeholders"]
    assert any("…" in p for p in body["placeholders"])
    assert "Họ và tên" in body["text_preview"]

    again = upload(client, admin, data, "Bản sao", "hop_dong")
    assert again.status_code == 409, again.text
    assert again.json()["id"] == body["id"]


def test_legal_basis_validated(client, admin, made, db):
    from sqlalchemy import select

    from app.db.models import LegalNode

    node_id = db.scalar(select(LegalNode.node_id).limit(1))
    assert node_id

    ok = upload(
        client, admin, docx_bytes("Mẫu quyết định …"), "Quyết định thử", "quyet_dinh",
        legal_basis=node_id,
    )
    assert ok.status_code == 201, ok.text
    body = ok.json()
    made.append(body["id"])
    assert body["legal_basis"] == [node_id]

    detail = client.get(f"/api/templates/{body['id']}", headers=admin).json()
    assert [n["node_id"] for n in detail["legal_basis_nodes"]] == [node_id]
    assert "display" in detail["legal_basis_nodes"][0]

    bad = upload(
        client, admin, docx_bytes("Mẫu đơn …"), "Đơn thử", "don",
        legal_basis="khong-co-node-nay",
    )
    assert bad.status_code == 422, bad.text


def test_search_kind_and_archive(client, admin, made):
    data = docx_bytes("Điều khoản XYZZY nội dung thử")
    resp = upload(client, admin, data, "Mẫu hợp đồng thử nghiệm", "hop_dong")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    made.append(body["id"])

    found = client.get("/api/templates", params={"q": "hop dong thu nghiem"}, headers=admin)
    assert found.status_code == 200
    assert body["id"] in [r["id"] for r in found.json()]

    by_kind = client.get("/api/templates", params={"kind": "hop_dong"}, headers=admin).json()
    assert body["id"] in [r["id"] for r in by_kind]
    other_kind = client.get("/api/templates", params={"kind": "don"}, headers=admin).json()
    assert body["id"] not in [r["id"] for r in other_kind]

    assert client.delete(f"/api/templates/{body['id']}", headers=admin).status_code == 200
    default = client.get("/api/templates", headers=admin).json()
    assert body["id"] not in [r["id"] for r in default]
    archived = client.get("/api/templates", params={"status": "archived"}, headers=admin).json()
    assert body["id"] in [r["id"] for r in archived]


def test_permissions(client, admin, user1):
    data = docx_bytes("Mẫu đơn xin nghỉ ……")
    assert upload(client, user1, data, "Đơn xin nghỉ", "don").status_code == 403
    assert client.get("/api/templates").status_code == 401
    assert client.get("/api/templates", headers=user1).status_code == 403
    assert client.get("/api/templates", headers=admin).status_code == 200


def test_templates_are_not_legal_nodes(client, admin, made, db):
    from app.rag.search import search_nodes

    data = docx_bytes("Nội dung đánh dấu XYZZYBIEUMAU không phải điều luật")
    resp = upload(client, admin, data, "Mẫu thông báo XYZZYBIEUMAU", "thong_bao")
    assert resp.status_code == 201, resp.text
    made.append(resp.json()["id"])

    hits = search_nodes(db, "XYZZYBIEUMAU", top_k=5, mode="bm25")
    assert all("XYZZYBIEUMAU" not in (hit.get("text") or "") for hit in hits)


def test_xlsx_reads_sheet_names():
    import zipfile

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr(
            "xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            "<sheets><sheet name=\"Bảng lương\" sheetId=\"1\"/></sheets></workbook>",
        )
    text = tpl.extract_text(out.getvalue(), "bang-luong.xlsx")
    assert "Bảng lương" in text
