"""Kiểm thử trích xuất văn bản từ tệp tải lên (upload-ocr-kg-plan, U2)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app.upload import extract as ex

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"
needs_ocr = pytest.mark.skipif(shutil.which("tesseract") is None, reason="thiếu tesseract")


def sample(name: str) -> bytes:
    path = SAMPLES / name
    if not path.exists():
        pytest.skip(f"thiếu mẫu {name}")
    return path.read_bytes()


def test_plain_txt():
    e = ex.extract(sample("hoi-dap-noi-bo.txt"), "hoi-dap-noi-bo.txt")
    assert e.mime == "text/plain"
    assert len(e.pages) == 1
    assert e.pages[0].method == "plain"
    assert "Điều 35" in e.text


def test_docx_paragraphs_and_table():
    e = ex.extract(sample("hop-dong-lao-dong-mau.docx"), "hop-dong-lao-dong-mau.docx")
    assert e.pages[0].method == "docx"
    assert "Điều 36" in e.text
    assert "Trần Thị Mẫu" in e.text  # nằm trong ô bảng


def test_pdf_text_layer_without_ocr():
    e = ex.extract(sample("noi-quy-lao-dong.pdf"), "noi-quy-lao-dong.pdf")
    assert e.mime == "application/pdf"
    assert all(p.method == "text" for p in e.pages)
    assert e.ocr_pages == 0
    assert "Điều 125" in e.text
    assert "KỶ LUẬT LAO ĐỘNG" in e.text


@needs_ocr
def test_scanned_jpg_is_ocr():
    e = ex.extract(sample("quyet-dinh-ky-luat-scan.jpg"), "quyet-dinh-ky-luat-scan.jpg")
    assert e.mime == "image/jpeg"
    assert len(e.pages) == 1
    assert e.pages[0].method == "ocr"
    assert e.mean_conf > 0.6
    low = e.text.lower()
    assert "bộ luật lao động" in low
    assert "điều 125" in low
    assert "kỷ luật" in low


@needs_ocr
def test_scanned_pdf_falls_back_to_ocr():
    e = ex.extract(
        sample("quyet-dinh-ky-luat-scan.pdf"), "quyet-dinh-ky-luat-scan.pdf"
    )
    assert e.ocr_pages == 1
    assert "Điều 125" in e.text


def test_unsupported_and_corrupt():
    with pytest.raises(ex.UnsupportedFile):
        ex.extract(b"MZ\x90\x00", "x.exe")
    with pytest.raises(ex.UnsupportedFile):
        ex.extract(b"%PDF-broken", "x.pdf")


def test_too_large(monkeypatch):
    monkeypatch.setattr(ex, "MAX_BYTES", 10)
    with pytest.raises(ex.TooLarge):
        ex.extract(b"x" * 11, "x.txt")


def test_multipage_pdf_page_numbers_footnotes_and_breaks():
    """Hồi quy: bản án nhiều trang (Án lệ 70 của Minh, 16/11/2026). Số trang ở đầu trang và
    chú thích cuối trang từng bị chèn vào giữa câu ngắt trang."""
    import re

    e = ex.extract(sample("ban-an-mau-nhieu-trang.pdf"), "ban-an-mau-nhieu-trang.pdf")
    assert len(e.pages) == 3 and e.ocr_pages == 0
    t = e.text
    assert len(t) > 2000  # dài hơn preview, phải lấy đủ
    assert not [ln for ln in t.split("\n") if re.fullmatch(r"\s*\d{1,3}\s*", ln)]  # không còn dòng số trang
    # câu bị ngắt trang nối liền, không bị chú thích chen vào giữa
    assert "07/2025/QĐ-\nNS chấm dứt hợp đồng" in t
    assert "￾" not in t
    # chú thích được giữ, dồn về cuối, có dấu [1] ở chỗ gốc
    assert t.rstrip().endswith("tính năng tải tài liệu lên.")
    assert "Chú thích:\n1 Bản án này là tài liệu hư cấu" in t
    assert "(tài liệu hư cấu để kiểm thử) [1]" in t
    assert " ".join(t.split()).count("câu cuối cùng của bản án mẫu") == 1


def test_clean_pdf_page_keeps_numbered_clauses():
    """Khoản luật "1. ..." không bị nhầm là chú thích hay số trang."""
    text, notes = ex._clean_pdf_page("5\nĐiều 3. Hình thức\n1. Khiển trách;\n2. Sa thải.")
    assert notes == []
    assert text == "Điều 3. Hình thức\n1. Khiển trách;\n2. Sa thải."
