"""Fixture dùng chung.

Ba tầng test, chạy được ở mọi máy mà không cần bí mật:
- không đánh dấu: thuần Python, luôn chạy
- @pytest.mark.db: cần Postgres có dữ liệu, tự bỏ qua nếu thiếu
- @pytest.mark.llm: gọi LLM thật, chỉ chạy khi RUN_LLM_TESTS=1
"""

from __future__ import annotations

import os

import pytest

# Test không bao giờ được quét mạng thật: tắt luồng quét tin mới (LI1) trước khi app được import,
# vì mọi TestClient(app) chạy lifespan và sẽ khởi động bộ hẹn giờ.
os.environ["INTEL_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def _auth_mode(request, monkeypatch):
    """Mọi test cũ chạy khi chưa bật đăng nhập; tests/test_auth.py tự bật lại."""
    from app.auth import deps

    on = str(request.fspath).replace("\\", "/").endswith("tests/test_auth.py")
    monkeypatch.setattr(deps.settings, "auth_required", on)


def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_LLM_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="gọi LLM thật; đặt RUN_LLM_TESTS=1 để chạy")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(scope="session")
def db():
    """Phiên DB tới kho đã nạp; bỏ qua cả nhóm test nếu không có."""
    from sqlalchemy import text

    from app.db.base import SessionLocal

    session = SessionLocal()
    try:
        n = session.execute(text("SELECT count(*) FROM legal_node")).scalar() or 0
    except Exception as exc:  # noqa: BLE001 - mọi lỗi kết nối đều có nghĩa là "không có DB"
        session.close()
        pytest.skip(f"không kết nối được Postgres: {exc.__class__.__name__}")
    if n == 0:
        session.close()
        pytest.skip("kho luật trống — chạy ingest trước")
    yield session
    session.close()


@pytest.fixture(autouse=True)
def _intel_side_effects_cleanup(request):
    """Test tin pháp luật (test_intel*.py) chạy trên DB dev: phân tích có thể tạo ca luật sư
    (review_case source=intel), dòng intel_impact/intel_doc và tệp tải lên (toàn văn). Xoá mọi
    dòng MỚI sinh trong test để không lẫn với dữ liệu quét thật."""
    if not request.node.fspath.basename.startswith("test_intel"):
        yield
        return
    try:
        from sqlalchemy import text

        from app.db.base import SessionLocal
    except Exception:  # noqa: BLE001
        yield
        return
    queries = {
        "review_case": "SELECT id FROM review_case WHERE source = 'intel'",
        "intel_impact": "SELECT item_id FROM intel_impact",
        "intel_doc": "SELECT item_id FROM intel_doc",
        "uploaded_file": "SELECT upload_id FROM uploaded_file",
    }
    keys = {"review_case": "id", "intel_impact": "item_id", "intel_doc": "item_id", "uploaded_file": "upload_id"}

    def snapshot():
        s = SessionLocal()
        try:
            out = {}
            for table, q in queries.items():
                try:
                    out[table] = {r[0] for r in s.execute(text(q))}
                except Exception:  # noqa: BLE001 — bảng chưa có thì bỏ qua
                    s.rollback()
                    out[table] = set()
            return out
        finally:
            s.close()

    before = snapshot()
    yield
    after = snapshot()
    new_uploads = after["uploaded_file"] - before["uploaded_file"]
    if new_uploads:
        from app.upload import service

        s = SessionLocal()
        try:
            for upload_id in new_uploads:
                service.remove_upload(s, upload_id)
        finally:
            s.close()
    s = SessionLocal()
    try:
        for table in ("intel_impact", "intel_doc", "review_case"):
            for key in after[table] - before[table]:
                s.execute(text(f"DELETE FROM {table} WHERE {keys[table]} = :k"), {"k": key})
        s.commit()
    finally:
        s.close()
