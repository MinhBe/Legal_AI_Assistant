"""Đăng nhập demo, phân quyền, hạn mức ngày, cloud_first cho VIP (contract AUTH1).

Cả tệp chạy với AUTH_REQUIRED=true — tests/conftest.py bật lại riêng cho tệp này.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.api import routes
from app.auth import accounts, quota, tokens
from app.auth.roles import ACCOUNTS
from app.llm import router as r
from app.llm.context import cloud_first_scope, data_class_scope
from app.main import app

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # chạy lifespan: tạo bảng + seed tài khoản demo
        yield c


@pytest.fixture(autouse=True)
def _clean_usage(client, db):
    """Bộ đếm của lần chạy trước không được làm hỏng lần này."""
    db.execute(text("DELETE FROM usage_count"))
    db.commit()


@pytest.fixture
def fake_chat(monkeypatch):
    """Pipeline giả: ghi lại tham số cloud_first để kiểm tra vai trò VIP."""
    calls: list[dict] = []

    def fake(message, history=None, mode="law", cloud_first=False, **kwargs):
        calls.append({"message": message, "cloud_first": cloud_first})
        yield "token", {"text": "trả lời thử"}
        yield "done", {}

    monkeypatch.setattr(routes, "run_chat", fake)
    return calls


def login(client: TestClient, username: str, password: str | None = None) -> str:
    resp = client.post(
        "/api/auth/login", json={"username": username, "password": password or username}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]


def H(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_passwords_are_stored_hashed(client, db):
    rows = db.execute(text("SELECT username, salt, pw_hash FROM app_user")).all()
    assert {row[0] for row in rows} >= set(ACCOUNTS)
    for username, salt, pw_hash in rows:
        assert len(salt) == 32 and len(pw_hash) == 64
        assert pw_hash != username and username not in pw_hash
    assert accounts.verify(db, "admin", "admin") is not None
    assert accounts.verify(db, "admin", "sai-mat-khau") is None


def test_login_and_token_states(client):
    ok = client.post("/api/auth/login", json={"username": "user1", "password": "user1"})
    assert ok.status_code == 200
    body = ok.json()
    assert body["role"] == "user" and body["daily"] == 50
    assert {"chat", "escalate"} <= set(body["perms"]) and body["token"]

    wrong = client.post("/api/auth/login", json={"username": "user1", "password": "sai"})
    assert wrong.status_code == 401

    tok = body["token"]
    tampered = tok[:-3] + ("AAA" if not tok.endswith("AAA") else "BBB")
    me = client.get("/api/auth/me", headers=H(tampered))
    assert me.status_code == 200 and me.json()["role"] == "anonymous"

    expired = tokens.issue("user1", "user", ttl_hours=-1)
    me = client.get("/api/auth/me", headers=H(expired))
    assert me.json()["role"] == "anonymous" and me.json()["username"] is None


def test_access_matrix(client, fake_chat):
    # khách vãng lai: chat + calc, không tải lên / đồ thị / duyệt / escalate
    assert client.post("/api/chat", json={"message": "thử"}).status_code == 200
    assert client.post(
        "/api/calc/severance", json={"avg_salary_6m": 10_000_000, "years": 2}
    ).status_code == 200
    assert client.post("/api/uploads", files={"file": ("a.txt", b"noi dung")}).status_code == 401
    assert client.get("/api/graph").status_code == 401
    assert client.get("/api/review/cases").status_code == 401
    assert client.post("/api/escalate", json={"question": "thử"}).status_code == 401

    guest2 = H(login(client, "guest2"))
    assert client.post(
        "/api/uploads", files={"file": ("a.txt", b"noi dung")}, headers=guest2
    ).status_code == 403
    assert client.post("/api/escalate", json={"question": "thử"}, headers=guest2).status_code == 403

    guest1 = H(login(client, "guest1"))
    assert client.post("/api/escalate", json={"question": "thử vip"}, headers=guest1).status_code == 200

    user1 = H(login(client, "user1"))
    assert client.post("/api/escalate", json={"question": "thử user"}, headers=user1).status_code == 200
    assert client.post(
        "/api/uploads", files={"file": ("a.txt", b"noi dung")}, headers=user1
    ).status_code == 403

    admin = H(login(client, "admin"))
    up = client.post("/api/uploads", files={"file": ("a.txt", b"noi dung")}, headers=admin)
    assert up.status_code in (200, 202), up.text
    assert client.get("/api/uploads", headers=admin).status_code == 200
    assert client.get("/api/graph", headers=admin).status_code == 200
    assert client.get("/api/review/cases", headers=admin).status_code == 200
    assert client.get("/api/dev/config", headers=admin).status_code == 403
    client.delete(f"/api/uploads/{up.json()['upload_id']}", headers=admin)

    dev = H(login(client, "dev"))
    assert client.get("/api/dev/config", headers=dev).status_code == 200


def test_dev_config_never_shows_secrets(client, monkeypatch):
    marker = "bi-mat-thu-nghiem-" + uuid.uuid4().hex
    monkeypatch.setattr(routes.get_settings(), "auth_secret", marker)
    dev = H(login(client, "dev"))
    resp = client.get("/api/dev/config", headers=dev)
    assert resp.status_code == 200
    assert marker not in resp.text
    body = resp.json()
    for name in ("auth_secret", "anthropic_api_key", "fpt_api_key", "deepseek_api_key",
                 "langfuse_secret_key", "database_url"):
        assert body[name] in ("đã đặt", "trống"), name


def test_quota_anonymous_per_client(client, fake_chat):
    mine = {"X-Client-Id": "t-" + uuid.uuid4().hex}
    for _ in range(10):
        assert client.post("/api/chat", json={"message": "hỏi"}, headers=mine).status_code == 200
    over = client.post("/api/chat", json={"message": "hỏi"}, headers=mine)
    assert over.status_code == 429
    assert "10 câu" in over.json()["detail"]
    assert client.get("/api/auth/me", headers=mine).json()["remaining"] == 0

    other = {"X-Client-Id": "t-" + uuid.uuid4().hex}
    assert client.post("/api/chat", json={"message": "hỏi"}, headers=other).status_code == 200


def test_guest_vip_has_no_daily_limit(db):
    user = {"username": "guest1", "role": "guest_vip", "client_id": "x"}
    for _ in range(30):
        assert quota.check_and_count(db, user) is None
    assert quota.remaining(db, user) is None


def test_vip_runs_cloud_first(client, fake_chat):
    guest1 = H(login(client, "guest1"))
    assert client.post("/api/chat", json={"message": "hỏi vip"}, headers=guest1).status_code == 200
    assert fake_chat[-1]["cloud_first"] is True

    user1 = H(login(client, "user1"))
    assert client.post("/api/chat", json={"message": "hỏi user"}, headers=user1).status_code == 200
    assert fake_chat[-1]["cloud_first"] is False


def test_level_b_stays_local_even_when_cloud_first(monkeypatch):
    monkeypatch.setattr(r.settings, "llm_legacy_race", False)
    monkeypatch.setattr(r.settings, "cloud_first_for_c", False)
    monkeypatch.setattr(r.settings, "local_model", "local-test")
    monkeypatch.setattr(r.settings, "cloud_llm_model", "cloud-test")
    monkeypatch.setattr(r.settings, "cloud_llm_fallback_models", "")
    monkeypatch.setattr(r.settings, "cloud_llm_keys_dir", "")
    monkeypatch.setattr(r.settings, "cloud_llm_api_key_env", "TEST_CLOUD_KEY")
    monkeypatch.setattr(r.settings, "deepseek_api_key", None)
    monkeypatch.setattr(r, "_LOCAL_CACHE", [0.0, None])
    monkeypatch.setattr(r, "_probe_local", lambda: True)
    monkeypatch.setenv("TEST_CLOUD_KEY", "k")
    router = r.LLMRouter()

    with data_class_scope("B"), cloud_first_scope(True):
        assert router._tiered_plan() == [("local", "local-test")]
    with data_class_scope("C"), cloud_first_scope(True):
        assert router._tiered_plan()[0][0] == "cloud"
    with data_class_scope("C"), cloud_first_scope(False):
        assert router._tiered_plan()[0][0] == "local"


@pytest.mark.db
def test_public_admin_password_override(db, monkeypatch):
    """Bản công khai: admin/dev đổi sang mật khẩu riêng, tài khoản thường giữ nguyên."""
    monkeypatch.setenv("LAWVN_ADMIN_PASSWORD", "mat-khau-rieng-test")
    try:
        accounts.seed(db)
        assert accounts.verify(db, "admin", "admin") is None
        assert accounts.verify(db, "admin", "mat-khau-rieng-test") is not None
        assert accounts.verify(db, "user1", "user1") is not None
    finally:
        monkeypatch.delenv("LAWVN_ADMIN_PASSWORD")
        accounts.seed(db)
    assert accounts.verify(db, "admin", "admin") is not None
