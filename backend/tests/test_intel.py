"""Tin pháp luật mới (LI1): parse fixture, tải lịch sự, lưu tăng dần, phân tích, API.

Không gọi mạng (httpx.MockTransport) và không gọi LLM thật (router giả).
Các test cần Postgres mang @pytest.mark.db và tự bỏ qua khi kho trống.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app.intel import analyze, fetch, scheduler, sources, store
from app.intel.fetch import Fetcher
from app.llm.context import get_cloud_first, get_data_class

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "legal-intel" / "2026-11-16"
TVPL_URL = "https://thuvienphapluat.vn/"
LVN_URL = "https://luatvietnam.vn/van-ban-moi.html"
ANLE_URL = "https://anle.toaan.gov.vn/"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _robots(**paths: str):
    """Handler: robots.txt cho phép tất cả, các path còn lại trả HTML đã cho."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return httpx.Response(200, text=paths.get(request.url.path, "<html></html>"))
    return handler


def _fake_fetcher(handler, cache_root=None):
    """Thay `scheduler.Fetcher`: giữ `allowed_urls` mà bộ quét truyền vào."""
    def make(*args, **kwargs):
        return Fetcher(
            "test-bot", 0.0, client=_client(handler), cache_root=cache_root,
            allowed_urls=kwargs.get("allowed_urls", ()),
        )
    return make


@pytest.fixture
def clean(db):
    """Bảng tin và lượt quét sạch trong lúc test, rồi trả lại dữ liệu thật như cũ
    (test chạy trên DB dev: không được xoá tin đã quét thật)."""
    # bảng sao thường (không TEMP): session trả kết nối về pool sau commit nên bảng TEMP sẽ mất.
    # Bảng con trước: intel_impact/intel_doc trỏ tới intel_item (xoá item sẽ kéo theo chúng).
    tables = ("intel_impact", "intel_doc", "intel_item", "intel_run")
    for table in tables:
        db.execute(text(f"DROP TABLE IF EXISTS _test_bk_{table}"))
        db.execute(text(f"CREATE TABLE _test_bk_{table} AS SELECT * FROM {table}"))
    for table in tables:
        db.execute(text(f"DELETE FROM {table}"))
    db.commit()
    yield
    db.rollback()
    for table in tables:
        db.execute(text(f"DELETE FROM {table}"))
    for table in reversed(tables):
        db.execute(text(f"INSERT INTO {table} SELECT * FROM _test_bk_{table}"))
    for table in tables:
        db.execute(text(f"DROP TABLE _test_bk_{table}"))
    db.commit()


# ---------- 1. đọc danh sách trên fixture ----------
def test_thuvienphapluat_finds_labor_documents():
    items = sources.ThuVienPhapLuat().parse(_html("thuvienphapluat_home.html"), TVPL_URL)
    assert len(items) >= 20
    assert len({i["url"] for i in items}) == len(items)
    minimum_wage = next(i for i in items if i["number"] == "399/2026/NĐ-CP")
    assert minimum_wage["category"] == "Lao-dong-Tien-luong"
    assert minimum_wage["kind"] == "Nghị định"
    assert minimum_wage["url"].startswith("https://thuvienphapluat.vn/van-ban/")
    assert sources.labor_hint(minimum_wage) is True
    # công văn nằm ở mục khác của trang chủ
    assert any(i["kind"] == "Công văn" for i in items)


def test_luatvietnam_returns_absolute_urls():
    items = sources.LuatVietnam().parse(_html("luatvietnam_van-ban-moi.html"), LVN_URL)
    assert len(items) >= 15
    assert len({i["url"] for i in items}) == len(items)
    assert all(i["url"].startswith("https://luatvietnam.vn/") for i in items)
    assert all(i["number"] for i in items)  # mọi link văn bản đều có số hiệu
    assert {i["kind"] for i in items} & {"Quyết định", "Luật", "Thông tư"}


def test_anle_needs_a_browser():
    adapter = sources.AnLe()
    assert adapter.parse(_html("anle_home.html"), ANLE_URL) == []
    assert adapter.last_status == "needs_browser"


# ---------- 2. tải: robots, giãn cách, 403 ----------
def test_robots_disallow_means_no_request(tmp_path):
    asked: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /van-ban/\n")
        return httpx.Response(200, text="<html><a>x</a></html>")

    fetcher = Fetcher(
        "test-bot", 0.0, client=_client(handler), cache_root=tmp_path, allowed_urls=(TVPL_URL,)
    )
    assert fetcher.get("https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/x.aspx") == (0, "")
    assert asked == ["/robots.txt"]  # chỉ hỏi robots.txt, không tải trang bị cấm
    assert fetcher.get(TVPL_URL)[0] == 200  # trang chủ vẫn được phép


def test_two_requests_to_one_host_are_spaced(tmp_path, monkeypatch):
    class Clock:
        now = 100.0
        slept = 0.0

    clock = Clock()

    def monotonic() -> float:
        return clock.now

    def sleep(seconds: float) -> None:
        clock.slept += seconds
        clock.now += seconds

    monkeypatch.setattr(fetch.time, "monotonic", monotonic)
    monkeypatch.setattr(fetch.time, "sleep", sleep)
    fetcher = Fetcher("test-bot", 3.0, client=_client(_robots()), cache_root=tmp_path)
    assert fetcher.get(TVPL_URL)[0] == 200
    assert fetcher.get(TVPL_URL)[0] == 200
    assert clock.slept >= 3.0


@pytest.mark.db
def test_forbidden_source_marks_the_run_blocked(db, clean, monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    monkeypatch.setattr(scheduler, "Fetcher", _fake_fetcher(handler))
    monkeypatch.setattr(analyze, "analyse_pending", lambda session: {})
    assert scheduler.run_scan("manual") is not None
    row = db.execute(text("SELECT per_source FROM intel_run ORDER BY id DESC LIMIT 1")).scalar()
    per_source = json.loads(row)
    assert per_source and all(v["status"] == "blocked" for v in per_source.values())
    assert per_source["thuvienphapluat"]["new"] == 0


# ---------- 3. lưu tăng dần ----------
@pytest.mark.db
def test_scan_twice_adds_each_item_once(db, clean, monkeypatch, tmp_path):
    handler = _robots(**{"/": _html("thuvienphapluat_home.html"),
                         "/van-ban-moi.html": _html("luatvietnam_van-ban-moi.html")})
    monkeypatch.setattr(
        scheduler, "Fetcher",
        _fake_fetcher(handler, cache_root=tmp_path),
    )
    monkeypatch.setattr(analyze, "analyse_pending", lambda session: {})
    scheduler.run_scan("manual")
    first = db.execute(text("SELECT count(*) FROM intel_item")).scalar()
    scheduler.run_scan("manual")
    second = db.execute(text("SELECT count(*) FROM intel_item")).scalar()
    assert first >= 20
    assert second == first


@pytest.mark.db
def test_number_already_in_corpus_is_flagged(db, clean):
    item = store.add_item(db, {
        "source": "thuvienphapluat",
        "url": "https://example.test/nd145",
        "title": "Nghị định 145/2020/NĐ-CP hướng dẫn Bộ luật Lao động",
        "number": "145/2020/NĐ-CP",
        "kind": "Nghị định",
        "labor_hint": True,
    })
    assert item is not None and item.in_corpus is True
    other = store.add_item(db, {
        "source": "thuvienphapluat",
        "url": "https://example.test/khong-co",
        "title": "Nghị định 9999/2026/NĐ-CP về thử nghiệm",
        "number": "9999/2026/NĐ-CP",
        "labor_hint": False,
    })
    assert other is not None and other.in_corpus is False
    assert store.add_item(db, {"url": "https://example.test/nd145", "title": "trùng"}) is None


# ---------- 4. phân tích ----------
HITS = [
    {
        "node_id": "blld2019-d90-k1",
        "display": "Khoản 1 Điều 90 (Bộ luật Lao động 2019)",
        "text": "Mức lương tối thiểu là mức thấp nhất được trả cho người lao động...",
    }
]


def _good(nodes: list[str]) -> dict:
    return {
        "relevant_labor": True,
        "topic": "Tiền lương tối thiểu",
        "summary": "Nghị định quy định mức lương tối thiểu vùng. Chưa có toàn văn nên chưa rõ chi tiết.",
        "what_changes": "chưa rõ — cần toàn văn",
        "amends": ["145/2020/NĐ-CP"],
        "replaces": [],
        "affected_nodes": nodes,
        "effective_date": "2026-12-01",
        "impact": "cao",
        "impact_reason": "Ảnh hưởng trực tiếp tiền lương của người lao động.",
        "routing": {"queue": "tiền lương", "action": "nạp ngay", "kg_updates": ["thêm văn bản"]},
        "needs_full_text": True,
        "confidence": 0.6,
    }


class FakeRouter:
    """Trả các câu trả lời đã định; câu cuối được dùng lại cho các lời gọi sau."""

    def __init__(self, replies: list) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def extract_json(self, messages, *, task: str = "answer", temperature: float = 0.0) -> dict:
        self.calls.append({
            "messages": messages,
            "task": task,
            "data_class": get_data_class(),
            "cloud_first": get_cloud_first(),
        })
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _labor_item(db, index: int = 0):
    return store.add_item(db, {
        "source": "thuvienphapluat",
        "url": f"https://example.test/tin-{index}",
        "title": "Nghị định 399/2026/NĐ-CP quy định mức lương tối thiểu cho người lao động",
        "number": f"399{index}/2026/NĐ-CP",
        "kind": "Nghị định",
        "category": "Lao-dong-Tien-luong",
        "labor_hint": True,
    })


@pytest.mark.db
def test_analysis_is_stored_and_unknown_nodes_dropped(db, clean, monkeypatch):
    item = _labor_item(db)
    monkeypatch.setattr(analyze, "search_nodes", lambda *a, **k: HITS)
    router = FakeRouter([_good(["blld2019-d90-k1", "node-khong-co-that"])])
    monkeypatch.setattr(analyze, "get_router", lambda: router)

    assert analyze.analyse(db, item) is True
    db.expire_all()
    saved = store.get_item(db, item.id)
    assert saved is not None and saved.status == "analysed" and saved.error is None
    data = json.loads(saved.analysis or "{}")
    assert data["affected_nodes"] == ["blld2019-d90-k1"]
    assert data["routing"]["action"] == "nạp ngay"
    # mức dữ liệu C + ưu tiên tuyến đám mây (Dahl) như contract yêu cầu
    assert router.calls[0]["data_class"] == "C"
    assert router.calls[0]["cloud_first"] is True


@pytest.mark.db
def test_analysis_retries_once_then_keeps_new(db, clean, monkeypatch):
    item = _labor_item(db)
    monkeypatch.setattr(analyze, "search_nodes", lambda *a, **k: HITS)
    broken = FakeRouter([{"relevant_labor": True}, {"relevant_labor": True}])
    monkeypatch.setattr(analyze, "get_router", lambda: broken)

    assert analyze.analyse(db, item) is False
    db.expire_all()
    failed = store.get_item(db, item.id)
    assert failed is not None
    assert failed.status == "new" and failed.error
    assert len(broken.calls) == 2  # đúng một lần thử lại, kèm lỗi schema

    retried = FakeRouter([{"relevant_labor": True}, _good([])])
    monkeypatch.setattr(analyze, "get_router", lambda: retried)
    assert analyze.analyse(db, item) is True
    assert len(retried.calls) == 2


@pytest.mark.db
def test_non_labor_and_in_corpus_are_skipped_without_llm(db, clean, monkeypatch):
    router = FakeRouter([_good([])])
    monkeypatch.setattr(analyze, "get_router", lambda: router)
    store.add_item(db, {
        "source": "luatvietnam",
        "url": "https://example.test/gia-dat",
        "title": "Quyết định 68/2026/QĐ-UBND về quản lý giá trên địa bàn tỉnh",
        "number": "68/2026/QĐ-UBND",
        "labor_hint": False,
    })
    store.add_item(db, {
        "source": "thuvienphapluat",
        "url": "https://example.test/nd145",
        "title": "Nghị định 145/2020/NĐ-CP hướng dẫn Bộ luật Lao động",
        "number": "145/2020/NĐ-CP",
        "labor_hint": True,
    })

    counts = analyze.analyse_pending(db)
    assert counts == {"analysed": 0, "skipped": 2, "failed": 0}
    assert router.calls == []


@pytest.mark.db
def test_at_most_ten_analyses_per_run(db, clean, monkeypatch):
    monkeypatch.setattr(analyze, "search_nodes", lambda *a, **k: HITS)
    router = FakeRouter([_good([])])
    monkeypatch.setattr(analyze, "get_router", lambda: router)
    for i in range(12):
        _labor_item(db, i)

    assert analyze.analyse_pending(db)["analysed"] == 10
    assert len(router.calls) == 10
    db.expire_all()
    counts = Counter(item.status for item in store.items(db))
    assert counts["analysed"] == 10
    assert counts["new"] == 2  # để lượt quét sau


# ---------- 5. API ----------
@pytest.fixture
def client(db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:  # chạy lifespan: tạo bảng + seed tài khoản
        yield test_client


def _token(client, username: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"username": username, "password": username})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.mark.db
def test_api_scan_requires_review_and_records_a_run(db, clean, client, monkeypatch):
    from app.auth import deps

    monkeypatch.setattr(deps.settings, "auth_required", True)

    def forbidden(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="forbidden")

    monkeypatch.setattr(
        scheduler, "Fetcher", _fake_fetcher(forbidden)
    )
    monkeypatch.setattr(analyze, "analyse_pending", lambda session: {})
    admin = _token(client, "admin")
    normal = _token(client, "user1")

    assert client.post("/api/intel/scan", headers=normal).status_code == 403
    scan = client.post("/api/intel/scan", headers=admin)
    assert scan.status_code == 202, scan.text
    runs = client.get("/api/intel/runs", headers=admin).json()
    assert runs and runs[0]["trigger"] == "manual"
    assert runs[0]["per_source"]["thuvienphapluat"]["status"] == "blocked"

    item = _labor_item(db)
    approved = client.post(f"/api/intel/items/{item.id}/approve", headers=admin)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] == "admin"
    ignored = client.post(f"/api/intel/items/{item.id}/ignore", headers=admin)
    assert ignored.status_code == 200 and ignored.json()["status"] == "ignored"
    listed = client.get("/api/intel/items?status=ignored&labor=true", headers=admin).json()
    assert [row["id"] for row in listed] == [item.id]
    assert client.get("/api/intel/items", headers=normal).status_code == 403


def test_tab_links_without_a_document_kind_are_dropped():
    from app.intel.sources import ThuVienPhapLuat

    html = (
        '<a href="/van-ban/Lao-dong-Tien-luong/Nghi-dinh-399-2026-ND-CP-abc-731671.aspx">Liên quan hiệu lực</a>'
        '<a href="/van-ban/Lao-dong-Tien-luong/Nghi-dinh-399-2026-ND-CP-abc-731671.aspx">'
        'Nghị định 399/2026/NĐ-CP quy định mức lương tối thiểu</a>'
        '<a href="/van-ban/Lao-dong-Tien-luong/Khac-1.aspx">Tải về bản PDF của văn bản này</a>'
    )
    items = ThuVienPhapLuat().parse(html, "https://thuvienphapluat.vn/")
    assert [i["title"] for i in items] == ["Nghị định 399/2026/NĐ-CP quy định mức lương tối thiểu"]
