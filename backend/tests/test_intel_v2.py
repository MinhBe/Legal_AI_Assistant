"""LI2 — nguồn tin v2: anle qua Playwright, toàn văn công khai, nhịp 6 giờ, watchlist.

Fixture HTML + mock httpx, không gọi mạng và không mở trình duyệt. Các test cần Postgres mang
@pytest.mark.db và tự bỏ qua khi kho trống.
"""

from __future__ import annotations

import ssl
from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text

from app import config
from app.db.models import IntelDoc, IntelItem, IntelRun, UploadedFile
from app.intel import analyze, fetch, fulltext, scheduler, sources, store, watchlist

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "legal-intel" / "2026-11-16"
SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"
ANLE_HOME = "https://anle.toaan.gov.vn/webcenter/portal/anle/home"
VBCP_HOME = "https://vanban.chinhphu.vn/"
TABLES = ("intel_doc", "intel_item", "intel_run")


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _fetcher(handler, tmp_path) -> fetch.Fetcher:
    """Fetcher với transport giả: robots cho phép tất cả, `handler` trả tệp/HTML."""
    def robots(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        return handler(request)

    return fetch.Fetcher("test-bot", 0.0, client=_client(robots), cache_root=tmp_path)


@pytest.fixture
def intel_clean(db):
    """Bảng tin/lượt quét/toàn văn sạch trong lúc test, trả lại dữ liệu thật sau đó.

    Tệp toàn văn đã nạp trong test bị xoá hẳn (không để văn bản rác trong kho dev).
    """
    IntelDoc.__table__.create(bind=db.get_bind(), checkfirst=True)
    for table in TABLES:
        db.execute(text(f"DROP TABLE IF EXISTS _v2_bk_{table}"))
        db.execute(text(f"CREATE TABLE _v2_bk_{table} AS SELECT * FROM {table}"))
        db.execute(text(f"DELETE FROM {table}"))
    db.commit()
    yield
    from app.upload import service as upload_service

    db.rollback()
    for upload_id in db.scalars(
        text("SELECT upload_id FROM intel_doc WHERE upload_id IS NOT NULL")
    ).all():
        upload_service.remove_upload(db, upload_id)
    for table in TABLES:
        db.execute(text(f"DELETE FROM {table}"))
    for table in reversed(TABLES):
        db.execute(text(f"INSERT INTO {table} SELECT * FROM _v2_bk_{table}"))
    for table in TABLES:
        db.execute(text(f"DROP TABLE _v2_bk_{table}"))
    db.commit()


# ---------- 1. chứng thư + client httpx ----------
def test_ssl_context_has_certifi_and_the_committed_intermediate():
    ctx = fetch.ssl_context()
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED
    subjects = " ".join(str(cert.get("subject")) for cert in ctx.get_ca_certs())
    assert "GlobalSign RSA OV SSL CA 2018" in subjects
    assert len(ctx.get_ca_certs()) > 100  # bundle certifi vẫn còn nguyên


def test_every_httpx_client_uses_the_shared_context(monkeypatch):
    seen: dict[str, object] = {}

    class Recorder:
        def __init__(self, *args, **kwargs):
            seen.update(kwargs)

    monkeypatch.setattr(fetch.httpx, "Client", Recorder)
    fetch.Fetcher("test-bot", 0.0)
    assert seen["verify"] is fetch.ssl_context()


# ---------- 2. anle đã render ----------
def test_anle_reads_rendered_home():
    items = sources.AnLe().parse(_html("anle_rendered_home.html"), ANLE_HOME)
    by_kind = {"Án lệ": [], "Dự thảo án lệ": [], "Nguồn án lệ": []}
    for item in items:
        by_kind.setdefault(item["kind"], []).append(item)
    assert len(by_kind["Án lệ"]) >= 5
    assert len(by_kind["Dự thảo án lệ"]) >= 3
    assert len(by_kind["Nguồn án lệ"]) >= 3

    first = next(i for i in by_kind["Án lệ"] if i["number"] == "84/2026/AL")
    assert first["doc_key"] == "TAND377305"
    assert first["title"].startswith("84/2026/AL: Về")
    assert first["url"].endswith("dDocName=TAND377305")
    assert sources.anle_pdf_url(first["doc_key"]) == (
        "https://anle.toaan.gov.vn/webcenter/ShowProperty?nodeId=/UCMServer/TAND377305"
    )
    assert any(i["number"] == "143/2025/DS-PT" for i in by_kind["Nguồn án lệ"])
    assert any(i["number"] == "DỰ THẢO 42/2026" for i in by_kind["Dự thảo án lệ"])


# ---------- 3. vanban.chinhphu ----------
def test_vanban_chinhphu_reads_the_new_document_table():
    items = sources.VanBanChinhPhu().parse(_html("vbcp_home_rows.html"), VBCP_HOME)
    assert len(items) >= 20
    assert len({i["number"] for i in items}) == len(items)  # mỗi số hiệu một item
    doc = next(i for i in items if i["number"] == "410/2026/NĐ-CP")
    assert doc["pdf_url"].startswith("https://datafiles.chinhphu.vn/")
    assert doc["pdf_url"].endswith(".pdf")
    assert doc["url"] == doc["pdf_url"]
    assert doc["listed_date"].isoformat() == "2026-11-12"
    assert doc["title"].startswith("410/2026/NĐ-CP Sửa đổi")


# ---------- 4. watchlist ----------
def test_priority_levels():
    numbers = {"145/2020/nđ-cp", "45/2019/qh14", "145/2020"}
    assert watchlist.priority(
        {
            "title": "Nghị định sửa đổi Nghị định 145/2020/NĐ-CP về hợp đồng lao động",
            "number": "10/2026/NĐ-CP",
        },
        numbers,
    ) == 3
    assert watchlist.priority(
        {"title": "Nghị định quy định mức lương tối thiểu vùng", "number": "399/2026/NĐ-CP"},
        numbers,
    ) == 2
    assert watchlist.priority(
        {"title": "Quyết định về quản lý giá đất trên địa bàn tỉnh", "number": "68/2026/QĐ-UBND"},
        numbers,
    ) == 0


@pytest.mark.db
def test_analysis_order_follows_priority(db, intel_clean, monkeypatch):
    numbers = watchlist.corpus_numbers(db)
    assert "145/2020/nđ-cp" in numbers  # số hiệu thật trong kho
    rows = [
        ("Thông tư 01/2026/TT-BLĐTBXH về quản lý lao động trong doanh nghiệp", "01/2026/TT-BLĐTBXH"),
        ("Nghị định 399/2026/NĐ-CP quy định mức lương tối thiểu vùng", "399/2026/NĐ-CP"),
        ("Nghị định 10/2026/NĐ-CP sửa đổi Nghị định 145/2020/NĐ-CP", "10/2026/NĐ-CP"),
    ]
    for index, (title, number) in enumerate(rows):
        store.add_item(db, {
            "source": "thuvienphapluat",
            "url": f"https://example.test/uu-tien-{index}",
            "title": title,
            "number": number,
            "labor_hint": True,
        })
    monkeypatch.setattr(analyze, "search_nodes", lambda *a, **k: [])
    router = FakeRouter([_good()])
    monkeypatch.setattr(analyze, "get_router", lambda: router)

    assert analyze.analyse_pending(db)["analysed"] == 3
    order = [call["title"] for call in router.calls]
    assert order == [rows[2][0], rows[1][0], rows[0][0]]  # 3 → 2 → 1


# ---------- 5. toàn văn ----------
@pytest.mark.db
def test_public_pdf_is_ingested_into_the_review_flow(db, intel_clean, monkeypatch, tmp_path):
    pdf = (SAMPLES / "noi-quy-lao-dong.pdf").read_bytes()
    fetcher = _fetcher(
        lambda request: httpx.Response(
            200, content=pdf, headers={"content-type": "application/pdf"}
        ),
        tmp_path,
    )
    item = _anle_item(db)
    counts = fulltext.scan(db, config.get_settings(), fetcher, {})

    db.expire_all()
    assert counts["ingested"] == 1
    doc = store.get_doc(db, item.id)
    assert doc is not None and doc.status == "ingested" and doc.error is None
    assert doc.source_url == sources.anle_pdf_url("TAND377305")
    upload = db.get(UploadedFile, doc.upload_id)
    assert upload is not None and upload.status == "pending_review"
    assert upload.filename.endswith(".pdf")
    # toàn văn đã trích đọc lại được cho bước phân tích
    assert fulltext.text_for(db, item.id)


@pytest.mark.db
def test_blocked_and_oversize_full_text_are_not_retried(db, intel_clean, monkeypatch, tmp_path):
    item = _anle_item(db)
    forbidden = _fetcher(lambda request: httpx.Response(403, text="forbidden"), tmp_path)
    counts = fulltext.scan(db, config.get_settings(), forbidden, {})
    db.expire_all()
    assert counts["blocked"] == 1
    doc = store.get_doc(db, item.id)
    assert doc is not None and doc.status == "blocked" and "403" in (doc.error or "")
    # đã có dòng: lượt sau không tải lại
    assert fulltext.scan(db, config.get_settings(), forbidden, {})["blocked"] == 0

    big = b"%PDF" + b"0" * (1024 * 1024 + 10)
    settings = config.get_settings()
    monkeypatch.setattr(settings, "intel_fulltext_max_mb", 1)
    huge = _fetcher(
        lambda request: httpx.Response(
            200, content=big, headers={"content-type": "application/pdf"}
        ),
        tmp_path,
    )
    other = _anle_item(db, key="TAND377340", number="90/2026/AL")
    counts = fulltext.scan(db, settings, huge, {})
    assert counts["failed"] == 1
    db.expire_all()
    doc = store.get_doc(db, other.id)
    assert doc is not None and doc.status == "failed" and "lớn hơn" in (doc.error or "")


# ---------- 6. nhịp quét ----------
@pytest.mark.db
def test_cadence_comes_from_intel_interval_hours(db, intel_clean, monkeypatch):
    settings = config.get_settings()
    monkeypatch.setattr(settings, "intel_interval_hours", 6)
    now = datetime.now(scheduler.TZ)

    db.add(IntelRun(trigger="schedule", started_at=now - timedelta(hours=1)))
    db.commit()
    assert scheduler.due_now(now) is False
    assert scheduler.next_run_at(now) > now
    assert scheduler.status()["interval_hours"] == 6

    db.execute(text("DELETE FROM intel_run"))
    db.add(IntelRun(trigger="schedule", started_at=now - timedelta(hours=7)))
    db.commit()
    assert scheduler.due_now(now) is True


def test_tests_never_start_the_scanner():
    assert config.get_settings().intel_enabled is False  # conftest đặt INTEL_ENABLED=false
    assert scheduler.is_running() is False


# ---------- tiện ích ----------
def _anle_item(db, key: str = "TAND377305", number: str = "84/2026/AL") -> IntelItem:
    item = store.add_item(db, {
        "source": "anle",
        "url": f"https://anle.toaan.gov.vn/webcenter/portal/anle/chitietanle?dDocName={key}",
        "title": f"{number}: Về chấm dứt việc nuôi con nuôi là người chưa thành niên",
        "number": number,
        "kind": "Án lệ",
        "labor_hint": True,
    })
    assert item is not None
    return item


def _good() -> dict:
    return {
        "relevant_labor": True,
        "topic": "Tiền lương tối thiểu",
        "summary": "Nghị định quy định mức lương tối thiểu vùng.",
        "what_changes": "chưa rõ — cần toàn văn",
        "amends": [],
        "replaces": [],
        "affected_nodes": [],
        "effective_date": None,
        "impact": "cao",
        "impact_reason": "Ảnh hưởng trực tiếp tiền lương.",
        "routing": {"queue": "tiền lương", "action": "nạp ngay", "kg_updates": []},
        "needs_full_text": True,
        "confidence": 0.5,
    }


class FakeRouter:
    """Ghi lại thứ tự gọi để kiểm tra thứ tự phân tích."""

    def __init__(self, replies: list[dict]) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def extract_json(self, messages, *, task: str = "answer", temperature: float = 0.0) -> dict:
        context = messages[1]["content"]
        title = context.split('"title": "', 1)[-1].split('",', 1)[0]
        self.calls.append({"title": title})
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
