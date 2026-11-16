"""Tệp tải lên: lưu tệp, nạp vào đồ thị, duyệt, xoá (upload-ocr-kg-plan, U4).

Mức A: chỉ đọc/ghi đĩa và Postgres — không gọi mạng, không gọi LLM.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.db.models import LegalDocument, LegalNode, UploadedFile
from app.upload.extract import TooLarge, UnsupportedFile, extract
from app.upload.ingest import delete_upload, ingest_upload, make_doc_id

UPLOAD_DIR = Path("/app/data/uploads")
PREVIEW_CHARS = 2000


def _path(sha256_hex: str, filename: str) -> Path:
    return UPLOAD_DIR / f"{sha256_hex}{Path(filename).suffix.lower()}"


def _text_path(sha256_hex: str) -> Path:
    return UPLOAD_DIR / f"{sha256_hex}.txt"


def full_text(db: Session, row: UploadedFile) -> str:
    """Toàn văn đã trích. Tệp tải lên trước khi có file .txt thì ghép lại từ node."""
    p = _text_path(row.sha256)
    if p.exists():
        return p.read_text(encoding="utf-8")
    if not row.doc_id:
        return row.preview or ""
    texts = db.scalars(
        select(LegalNode.text).where(LegalNode.doc_id == row.doc_id).order_by(LegalNode.seq)
    ).all()
    return "\n\n".join(t for t in texts if t)


def save_upload(
    db: Session, data: bytes, filename: str, title: str | None = None
) -> UploadedFile:
    """Lưu tệp rồi nạp thành node; tệp trùng (cùng sha256) trả lại row cũ."""
    sha = hashlib.sha256(data).hexdigest()
    row = db.scalar(select(UploadedFile).where(UploadedFile.sha256 == sha))
    if row is not None and row.status != "failed":
        row.duplicate = True
        return row

    if row is None:  # tệp mới, hoặc lần trước lỗi -> thử lại trên cùng row
        row = UploadedFile(
            upload_id=uuid.uuid4().hex, sha256=sha, filename=filename, size_bytes=len(data)
        )
        db.add(row)
    row.duplicate = False
    row.filename = filename
    row.size_bytes = len(data)
    upload_id = row.upload_id

    try:
        e = extract(data, filename)
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _path(sha, filename).write_bytes(data)
        _text_path(sha).write_text(e.text, encoding="utf-8")  # toàn văn; preview chỉ là đoạn đầu
        res = ingest_upload(
            db,
            doc_id=make_doc_id(sha),
            title=title or Path(filename).stem,
            text=e.text,
            filename=filename,
        )
    except (UnsupportedFile, TooLarge):
        db.rollback()  # không để lại row cho tệp bị từ chối
        raise
    except Exception as exc:  # noqa: BLE001 - mọi lỗi khác: ghi row failed để người dùng thấy
        db.rollback()
        row = db.get(UploadedFile, upload_id)
        if row is None:  # row mới chưa từng được commit
            row = UploadedFile(upload_id=upload_id, sha256=sha)
            db.add(row)
        row.filename = filename
        row.size_bytes = len(data)
        row.status = "failed"
        row.error = str(exc)[:500]
        db.commit()
        return row

    row = db.get(UploadedFile, upload_id)
    row.doc_id = res["doc_id"]
    row.mime = e.mime
    row.pages = len(e.pages)
    row.ocr_pages = e.ocr_pages
    row.chars = len(e.text)
    row.mean_ocr_conf = e.mean_conf
    row.parse_mode = res["parse_mode"]
    row.n_nodes = res["n_nodes"]
    row.n_refs = res["n_refs"]
    row.status = "pending_review"
    row.error = None
    row.preview = e.text[:PREVIEW_CHARS]
    row.duplicate = False
    db.commit()
    return row


def set_status(db: Session, upload_id: str, status: str) -> UploadedFile:
    """Duyệt / từ chối; trạng thái văn bản đã nạp đổi theo."""
    row = db.get(UploadedFile, upload_id)
    row.status = status
    row.reviewed_at = datetime.now(UTC)
    if row.doc_id:
        db.execute(
            update(LegalDocument)
            .where(LegalDocument.doc_id == row.doc_id)
            .values(status=status)
        )
    db.commit()
    return row


def remove_upload(db: Session, upload_id: str) -> None:
    """Xoá văn bản (node + dẫn chiếu), tệp trên đĩa, rồi row."""
    row = db.get(UploadedFile, upload_id)
    if row is None:
        return
    doc_id = row.doc_id
    # Xoá row trước: FK legal_document CASCADE sẽ xoá luôn nó nếu xoá văn bản trước.
    db.execute(delete(UploadedFile).where(UploadedFile.upload_id == upload_id))
    if doc_id:
        delete_upload(db, doc_id)
    _path(row.sha256, row.filename).unlink(missing_ok=True)
    _text_path(row.sha256).unlink(missing_ok=True)
    db.commit()


def to_dict(u: UploadedFile) -> dict:
    return {
        "upload_id": u.upload_id,
        "doc_id": u.doc_id,
        "filename": u.filename,
        "mime": u.mime,
        "sha256": u.sha256,
        "size_bytes": u.size_bytes,
        "pages": u.pages,
        "ocr_pages": u.ocr_pages,
        "chars": u.chars,
        "mean_ocr_conf": u.mean_ocr_conf,
        "parse_mode": u.parse_mode,
        "n_nodes": u.n_nodes,
        "n_refs": u.n_refs,
        "data_class": u.data_class,
        "status": u.status,
        "error": u.error,
        "preview": u.preview,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "reviewed_at": u.reviewed_at.isoformat() if u.reviewed_at else None,
        "duplicate": bool(getattr(u, "duplicate", False)),
    }
