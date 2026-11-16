"""LI3 — toàn văn chính thức theo số hiệu (Công báo) + danh mục án lệ anle.

Fixture HTML viết tại chỗ theo sự thật đo ngày 2026-11-16, mock `render`/httpx:
không gọi mạng, không mở trình duyệt. Test cần Postgres mang @pytest.mark.db.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest
from sqlalchemy import text
from urllib.parse import quote

from app import config
from app.db.models import IntelDoc, IntelItem, PrecedentCatalog
from app.intel import fetch, fulltext, licensed, official, precedents, sources, store

FIXTURES = Path(__file__).resolve().parents[1] / "data" / "fixtures" / "legal-intel" / "2026-11-16"
SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"
NUMBER = "399/2026/NĐ-CP"
PAGE_URL = "https://congbao.chinhphu.vn/van-ban/nghi-dinh-quy-dinh-muc-luong-toi-thieu-vung-12345.htm"
SEARCH_URL = official.SEARCH_URL.format(keyword=quote(NUMBER))
DOCX_URL = "https://g7.cdnchinhphu.vn/api/download/stream?Url=/2026_576_399/2026/ND-CP.docx"
PDF_URL = "https://g7.cdnchinhphu.vn/api/download/stream?Url=/2026_576_399/2026/ND-CP.pdf"

HOME = f"""<html><body>
<a href="/van-ban/thong-tu-khac-99999.htm">Thông tư 01/2026/TT-BLĐTBXH hướng dẫn luật lao động</a>
<a href="{PAGE_URL}">Nghị định {NUMBER} quy định mức lương tối thiểu vùng</a>
</body></html>"""
DETAIL = f"""<html><body><h2>Nghị định {NUMBER}</h2>
<p>Hiệu lực: 01/01/2027</p>
<a href="{PDF_URL}">2026_576_399/2026/NĐ-CP.pdf</a>
<a href="{DOCX_URL}">2026_576_399/2026/NĐ-CP.docx</a>
</body></html>"""

# bảng con trước (xoá trước, khôi phục sau): intel_doc/intel_impact trỏ tới intel_item
TABLES = ("precedent_catalog", "intel_impact", "intel_doc", "intel_item", "intel_run")


@pytest.fixture
def clean(db):
    """Bảng tin/lượt quét/toàn văn/danh mục sạch trong lúc test, trả lại dữ liệu thật sau đó."""
    for table in ("precedent_catalog", "intel_doc"):
        db.execute(text(f"CREATE TABLE IF NOT EXISTS {table} AS SELECT * FROM {table} LIMIT 0"))
    IntelDoc.__table__.create(bind=db.get_bind(), checkfirst=True)
    PrecedentCatalog.__table__.create(bind=db.get_bind(), checkfirst=True)
    for table in TABLES:
        db.execute(text(f"DROP TABLE IF EXISTS _l3_bk_{table}"))
        db.execute(text(f"CREATE TABLE _l3_bk_{table} AS SELECT * FROM {table}"))
        db.execute(text(f"DELETE FROM {table}"))
    db.commit()
    yield
    from app.upload import service as upload_service

    db.rollback()
    ids = db.scalars(
        text(
            "SELECT upload_id FROM intel_doc WHERE upload_id IS NOT NULL "
            "UNION SELECT upload_id FROM precedent_catalog WHERE upload_id IS NOT NULL"
        )
    ).all()
    for upload_id in ids:
        upload_service.remove_upload(db, upload_id)
    for table in TABLES:
        db.execute(text(f"DELETE FROM {table}"))
    for table in reversed(TABLES):
        db.execute(text(f"INSERT INTO {table} SELECT * FROM _l3_bk_{table}"))
    for table in TABLES:
        db.execute(text(f"DROP TABLE _l3_bk_{table}"))
    db.commit()


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def _robots(**paths: tuple[bytes, str]):
    """robots.txt cho phép tất cả; các URL còn lại trả bytes theo tiền tố đường dẫn."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\n")
        for needle, (body, mime) in paths.items():
            if needle in str(request.url):
                return httpx.Response(200, content=body, headers={"content-type": mime})
        return httpx.Response(404, text="not found")

    return handler


def _fetcher(handler, tmp_path, delay: float = 0.0) -> fetch.Fetcher:
    return fetch.Fetcher("test-bot", delay, client=_client(handler), cache_root=tmp_path)


def _render(pages: dict[str, str], calls: list[str] | None = None):
    """Hàm render giả: URL chứa khoá nào thì trả trang đó (không khớp: trang rỗng)."""

    def render(url: str) -> str:
        if calls is not None:
            calls.append(url)
        for needle, html in pages.items():
            if needle in url:
                return html
        return "<html><body></body></html>"

    return render


# ---------- 1. đọc trang Công báo ----------
def test_congbao_lookup_prefers_docx_and_reads_effective_date():
    calls: list[str] = []
    found = official.congbao_lookup(NUMBER, _render({PAGE_URL: DETAIL, "congbao.chinhphu.vn/": HOME}, calls))

    assert found is not None
    assert found["page_url"] == PAGE_URL
    assert [f["ext"] for f in found["files"]] == ["docx", "pdf"]  # DOCX trước
    assert found["files"][0]["name"].endswith("NĐ-CP.docx")
    assert found["files"][0]["url"] == DOCX_URL
    assert found["effective_date"] == date(2027, 1, 1)
    assert calls[0] == official.CONGBAO_HOME  # trang chủ trước
    assert PAGE_URL in calls[1]  # rồi mở trang văn bản


def test_congbao_lookup_falls_back_to_the_keyword_search():
    calls: list[str] = []
    render = _render({SEARCH_URL: f'<a href="{PAGE_URL}">Nghị định {NUMBER}</a>', PAGE_URL: DETAIL}, calls)
    found = official.congbao_lookup(NUMBER, render)

    assert found is not None and found["page_url"] == PAGE_URL
    assert SEARCH_URL in calls  # đã gửi ô tìm kiếm với số hiệu
    assert official.congbao_lookup("999/2026/QĐ-XYZ", _render({})) is None
    assert official.congbao_lookup(NUMBER, None) is None


def test_parse_files_ignores_other_documents():
    html = (
        f'<a href="{DOCX_URL}">2026_576_399/2026/NĐ-CP.docx</a>'
        '<a href="https://g7.cdnchinhphu.vn/api/download/stream?Url=/2026_1_ABC/2026/ABC.pdf">'
        "2026_1_ABC/2026/ABC.pdf</a>"
        '<a href="https://example.test/tai-ve.htm">tải về</a>'
    )
    files = official.parse_files(html, PAGE_URL, NUMBER)
    assert [f["name"] for f in files] == ["2026_576_399/2026/NĐ-CP.docx"]
    assert official.effective_date("<p>Hiệu lực: 31/02/2027</p>") is None  # ngày không có thật


def test_vbpl_is_a_stub_because_robots_disallows_search():
    stub = sources.Vbpl()
    assert stub.listing_urls == () and stub.last_status == "robots_disallow"
    assert stub.parse("<html></html>", "https://vbpl.vn/") == []


# ---------- 2. thứ tự nguồn toàn văn ----------
@pytest.mark.db
def test_fulltext_source_order_and_not_found(db, clean, monkeypatch, tmp_path):
    pdf = (SAMPLES / "noi-quy-lao-dong.pdf").read_bytes()
    docx = (SAMPLES / "hop-dong-lao-dong-mau.docx").read_bytes()
    mime = {
        "content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }
    fetcher = _fetcher(
        _robots(
            **{
                "ShowProperty": (pdf, "application/pdf"),
                "datafiles.chinhphu.vn": (pdf, "application/pdf"),
                "cdnchinhphu.vn": (docx, mime["content-type"]),
            }
        ),
        tmp_path,
    )
    anle = _item(db, "anle", "https://anle.toaan.gov.vn/webcenter/portal/anle/chitietanle?dDocName=TAND377305",
                 "84/2026/AL: Về việc sa thải người lao động")
    decree = _item(db, "thuvienphapluat", "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/410.aspx",
                   "Nghị định 410/2026/NĐ-CP về tiền lương")
    congbao = _item(db, "thuvienphapluat", "https://thuvienphapluat.vn/van-ban/Lao-dong-Tien-luong/399.aspx",
                    f"Nghị định {NUMBER} quy định mức lương tối thiểu vùng")
    missing = _item(db, "luatvietnam", "https://luatvietnam.vn/van-ban/missing-1.html",
                    "Quyết định 999/2026/QĐ-XYZ về tiền lương")
    calls: list[str] = []
    render = _render({PAGE_URL: DETAIL, "congbao.chinhphu.vn/": HOME}, calls)

    counts = fulltext.scan(
        db,
        config.get_settings(),
        fetcher,
        {"410/2026/nđ-cp": "https://datafiles.chinhphu.vn/410-2026.pdf"},
        render=render,
    )

    assert counts["ingested"] == 3, counts
    assert counts["not_found"] == 1
    docs = {item.id: store.get_doc(db, item.id) for item in (anle, decree, congbao, missing)}
    assert docs[anle.id].source_url == "https://anle.toaan.gov.vn/webcenter/ShowProperty?nodeId=/UCMServer/TAND377305"
    assert docs[decree.id].source_url == "https://datafiles.chinhphu.vn/410-2026.pdf"
    assert docs[congbao.id].source_url == DOCX_URL  # DOCX của Công báo trước PDF
    assert docs[missing.id].status == "not_found"
    assert len(calls) == 4  # chỉ tra Công báo cho 2 tin không có nguồn nào khác (trang chủ + tìm kiếm)
    # ngày hiệu lực do code đọc, nằm trong ngữ cảnh phân tích
    assert fulltext.text_for(db, congbao.id).startswith("Hiệu lực: 2027-01-01")


@pytest.mark.db
def test_congbao_lookups_are_capped(db, clean, tmp_path):
    for index in range(7):
        _item(
            db,
            "luatvietnam",
            f"https://luatvietnam.vn/van-ban/khong-co-{index}-d1.html",
            f"Nghị định {500 + index}/2026/NĐ-CP về tiền lương",
        )
    calls: list[str] = []
    fetcher = _fetcher(_robots(), tmp_path)

    counts = fulltext.scan(db, config.get_settings(), fetcher, {}, render=_render({}, calls))

    assert counts["not_found"] == 7  # không nguồn nào có: ghi trạng thái, không ném lỗi
    assert len(calls) == 2 * fulltext.MAX_CONGBAO_LOOKUPS  # mỗi lượt tra: trang chủ + tìm kiếm


# ---------- 3. danh mục án lệ ----------
def test_anle_catalogue_reads_the_list_page():
    # fixture giữ 40 link của trang 1 = 10 án lệ × 4 link (số hiệu, tiêu đề, thuộc tính, liên quan)
    rows = precedents.parse_list((FIXTURES / "anle_list_page1.html").read_text(encoding="utf-8"))
    assert len(rows) == 10
    assert len({row["doc_key"] for row in rows}) == len(rows)
    assert rows[0]["number"] == "90/2026/AL"
    assert rows[0]["doc_key"] == "TAND377340"
    assert rows[0]["title"].startswith("Về thẩm quyền hủy giấy chứng nhận")
    assert rows[0]["file_url"] == "https://anle.toaan.gov.vn/webcenter/ShowProperty?nodeId=/UCMServer/TAND377340"
    assert all(row["doc_key"] and row["number"] and row["title"] for row in rows)


@pytest.mark.db
def test_catalogue_paging_stops_and_status_is_detected(db, clean, tmp_path):
    list_html = """<html><body>
<a href="http://anle.toaan.gov.vn/webcenter/portal/anle/chitietanle?dDocName=TAND1">90/2026/AL</a>
<a href="http://anle.toaan.gov.vn/webcenter/portal/anle/chitietanle?dDocName=TAND1">Về việc sa thải người lao động trái pháp luật</a>
<a href="http://anle.toaan.gov.vn/webcenter/portal/anle/chitietanle?dDocName=TAND2">89/2026/AL</a>
<a href="http://anle.toaan.gov.vn/webcenter/portal/anle/chitietanle?dDocName=TAND2">Về bồi thường thiệt hại do vi phạm hợp đồng</a>
</body></html>"""
    cancelled = "<p>Án lệ số 90/2026/AL đã bị bãi bỏ theo Nghị quyết của Hội đồng Thẩm phán.</p>"
    normal = "<p>Án lệ 89/2026/AL đang có hiệu lực.</p>"
    calls: list[str] = []
    render = _render(
        {"TAND1": cancelled, "TAND2": normal, "selectedPage=1": list_html, "selectedPage=2": list_html},
        calls,
    )
    fetcher = _fetcher(_robots(), tmp_path)  # tệp án lệ 404: chưa có toàn văn, không sao

    counts = precedents.crawl(render, fetcher, db)

    assert counts["pages"] == 1  # trang 2 không thêm gì mới -> dừng
    assert counts["new"] == 2
    assert db.get(PrecedentCatalog, "TAND1").status == "bi_huy_bo"
    assert "bãi bỏ" in db.get(PrecedentCatalog, "TAND1").status_note
    assert db.get(PrecedentCatalog, "TAND2").status == "dang_ap_dung"
    assert counts["uploaded"] == 0  # tệp không tải được thì để lượt sau


# ---------- 4. chỗ cắm API trả phí ----------
def test_licensed_source_is_off_by_default(monkeypatch):
    settings = config.get_settings()
    monkeypatch.setattr(settings, "licensed_api_provider", "")
    assert licensed.get_licensed() is None

    monkeypatch.setattr(settings, "licensed_api_provider", "thuvienphapluat")
    monkeypatch.setattr(settings, "licensed_api_key_env", "LI3_TEST_KEY")
    monkeypatch.delenv("LI3_TEST_KEY", raising=False)
    assert licensed.get_licensed() is None  # thiếu khoá = tắt

    def _never_read(_dir):
        raise AssertionError("không được đọc thư mục keys/")

    monkeypatch.setattr(config, "load_key_dir", _never_read)
    monkeypatch.setenv("LI3_TEST_KEY", "dummy")
    assert licensed.get_licensed() is None  # chưa có lớp hiện thực nào


# ---------- tiện ích ----------
def _item(db, source: str, url: str, title: str) -> IntelItem:
    item = store.add_item(
        db,
        {
            "source": source,
            "url": url,
            "title": title,
            "number": sources.doc_number(title),
            "kind": "Nghị định",
            "labor_hint": True,
        },
    )
    assert item is not None and item.number
    return item
