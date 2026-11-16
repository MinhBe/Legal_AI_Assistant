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
