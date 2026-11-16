"""LI4 — thư mục inbox cho tệp luật sư tự tải về.

Test trên thư mục tạm và tệp mẫu trong `data/samples/upload/`; cần Postgres mang
@pytest.mark.db. Dòng `intel_item`/`intel_doc` và tệp tải lên sinh trong test được dọn sau đó.
"""

from __future__ import annotations

import os
import time
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import text

from app.db.models import UploadedFile
from app.intel import inbox, store

SAMPLES = Path(__file__).resolve().parents[1] / "data" / "samples" / "upload"
ZERO = {"ingested": 0, "matched": 0, "failed": 0, "skipped": 0}


@pytest.fixture
def clean(db):
    """Dữ liệu tin/toàn văn/tệp tải lên có trước test được giữ nguyên; dòng mới bị xoá."""

    def ids(table: str, key: str) -> set[str]:
        return {row[0] for row in db.execute(text(f"SELECT {key} FROM {table}"))}

    before = {
        "uploaded_file": ids("uploaded_file", "upload_id"),
        "intel_doc": ids("intel_doc", "item_id"),
        "intel_item": ids("intel_item", "id"),
    }
    yield
    from app.upload import service as upload_service

    db.rollback()
    for upload_id in ids("uploaded_file", "upload_id") - before["uploaded_file"]:
        upload_service.remove_upload(db, upload_id)
    for item_id in ids("intel_item", "id") - before["intel_item"]:
        db.execute(text("DELETE FROM intel_doc WHERE item_id = :i"), {"i": item_id})
        db.execute(text("DELETE FROM intel_item WHERE id = :i"), {"i": item_id})
    for item_id in ids("intel_doc", "item_id") - before["intel_doc"]:
        db.execute(text("DELETE FROM intel_doc WHERE item_id = :i"), {"i": item_id})
    db.commit()


def _place(path: Path, data: bytes | str) -> None:
    """Ghi tệp rồi lùi mtime để không bị coi là còn đang ghi."""
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    old = time.time() - 60
    os.utime(path, (old, old))


def _item(db, number: str, title: str):
    item = store.add_item(
        db,
        {
            "source": "thuvienphapluat",
            "url": f"https://example.test/inbox-{time.time_ns()}",
            "title": title,
            "number": number,
            "kind": "Nghị định",
            "labor_hint": True,
        },
    )
    assert item is not None
    return item


# ---------- 1. số hiệu trong tên tệp ----------
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("399-2026-ND-CP.pdf", "399/2026/NĐ-CP"),
        ("399_2026_NĐ-CP.pdf", "399/2026/NĐ-CP"),
        ("NĐ 399/2026.pdf", "399/2026/NĐ-CP"),
        ("Nghi dinh 399 2026.pdf", "399/2026/NĐ-CP"),
        ("399-2026-ND-CP (1).docx", "399/2026/NĐ-CP"),
        ("noi-quy-lao-dong.pdf", ""),
        ("bien-ban-hop.txt", ""),
    ],
)
def test_number_from_name(filename, expected):
    assert inbox.number_from_name(filename) == expected


# ---------- 2. tệp có số hiệu trong tên ----------
@pytest.mark.db
def test_pdf_named_with_number_is_ingested_and_matched(db, clean, tmp_path):
    # số hiệu riêng cho lượt chạy này để không đụng tin thật trong DB dev
    number = f"{time.time_ns() % 1_000_000}/2999/NĐ-CP"
    filename = f"{number.split('/')[0]}-2999-ND-CP.pdf"
    item = _item(db, number, f"Nghị định {number} về tiền lương")
    store.set_status(db, item, "analysed")
    root = tmp_path / "inbox"
    root.mkdir()
    _place(root / filename, (SAMPLES / "noi-quy-lao-dong.pdf").read_bytes())

    counts = inbox.scan_inbox(db, root)

    assert counts == {"ingested": 1, "matched": 1, "failed": 0, "skipped": 0}
    doc = store.get_doc(db, item.id)
    assert doc is not None and doc.status == "ingested"
    assert doc.source_url == f"inbox:{filename}"
    row = db.get(UploadedFile, doc.upload_id)
    assert row is not None and row.status == "pending_review"
    assert item.status == "new"  # phân tích lại bằng toàn văn
    assert (root / "done" / date.today().isoformat() / filename).exists()
    assert not (root / filename).exists()


# ---------- 3. số hiệu chỉ có trong nội dung ----------
@pytest.mark.db
def test_number_is_found_in_the_extracted_text(db, clean, tmp_path):
    number = f"{time.time_ns() % 1_000_000}/2998/NĐ-CP"
    item = _item(db, number, f"Nghị định {number} về điều kiện lao động")
    body = (SAMPLES / "hoi-dap-noi-bo.txt").read_text(encoding="utf-8")
    root = tmp_path / "inbox"
    root.mkdir()
    _place(
        root / "toan-van-nghi-dinh.txt",
        f"Nghị định số {number} về điều kiện lao động\n\n" + body,
    )

    counts = inbox.scan_inbox(db, root)

    assert counts["ingested"] == 1 and counts["matched"] == 1
    doc = store.get_doc(db, item.id)
    assert doc is not None and doc.status == "ingested"
    assert store.item_dict(db, item)["fulltext"]["source_url"] == "inbox:toan-van-nghi-dinh.txt"


# ---------- 4. tệp xấu, tệp lạ, tệp đang ghi ----------
@pytest.mark.db
def test_unsupported_hidden_partial_and_corrupt_files(db, clean, tmp_path):
    root = tmp_path / "inbox"
    root.mkdir()
    (root / "anh.jpg").write_bytes((SAMPLES / "quyet-dinh-ky-luat-scan.jpg").read_bytes())
    (root / ".an.pdf").write_bytes(b"%PDF-1.4\n")
    (root / "~$tam.docx").write_bytes(b"x")
    _place(root / "hong.pdf", b"%PDF-1.4\nkhong phai pdf that")
    fresh = root / "dang-ghi.pdf"
    fresh.write_bytes((SAMPLES / "noi-quy-lao-dong.pdf").read_bytes())
    now = time.time()
    os.utime(fresh, (now, now))

    counts = inbox.scan_inbox(db, root)

    assert counts == {"ingested": 0, "matched": 0, "failed": 1, "skipped": 4}
    assert (root / "anh.jpg").exists()  # đuôi lạ: để nguyên
    assert (root / ".an.pdf").exists() and (root / "~$tam.docx").exists()
    assert fresh.exists()  # còn đang ghi: để lượt sau
    assert (root / "failed" / "hong.pdf").exists()
    error = (root / "failed" / "hong.pdf.error.txt").read_text(encoding="utf-8")
    assert error.strip()
    # thư mục không tồn tại: không raise
    assert inbox.scan_inbox(db, tmp_path / "khong-co") == ZERO
