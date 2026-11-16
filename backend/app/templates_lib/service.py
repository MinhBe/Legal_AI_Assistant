"""Biểu mẫu tải lên (TPL1): đọc chữ để tìm chỗ trống, tìm kiếm, lưu tệp.

Biểu mẫu KHÔNG phải văn bản luật: chỉ nằm ở bảng `template`, không vào `legal_node`
nên không bao giờ lọt vào `search_nodes` hay knowledge graph.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agent.guard import normalize
from app.db.models import LegalNode, Template

TEMPLATE_DIR = Path("/app/data/templates")
MAX_BYTES = 20 * 1024 * 1024
KINDS = ("hop_dong", "quyet_dinh", "don", "bien_ban", "thong_bao", "quy_che", "khac")
SUFFIXES = {".docx": None, ".pdf": "application/pdf", ".xlsx": None, ".doc": "application/msword"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PREVIEW_CHARS = 1500

# Chỗ cần điền: {{tên}}, [tên], và dãy dấu chấm "……"
_PLACEHOLDER = re.compile(r"\{\{[^{}\n]{1,80}\}\}|\[[^\[\]\n]{1,80}\]|…{2,}")


class TemplateError(ValueError):
    """Tệp không hợp lệ (định dạng, kích thước, nội dung)."""


def detect_placeholders(text: str) -> list[str]:
    """Các chỗ trống tìm thấy trong biểu mẫu — chỉ nhận diện, chưa điền."""
    out: list[str] = []
    for found in _PLACEHOLDER.findall(text):
        if found not in out:
            out.append(found)
    return out


def extract_text(data: bytes, filename: str) -> str:
    """Chữ của biểu mẫu để tìm kiếm và đếm chỗ trống. `.doc` nhị phân: chưa trích."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".docx":
        import docx

        document = docx.Document(io.BytesIO(data))
        parts = [p.text for p in document.paragraphs]
        for table in document.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    if suffix == ".pdf":
        import pypdfium2 as pdfium

        document = pdfium.PdfDocument(data)
        return "\n".join(page.get_textpage().get_text_range() for page in document)
    if suffix == ".xlsx":
        # shortcut: chỉ đọc tên trang, dữ liệu ô chưa trích — nâng cấp khi cần tìm trong ô
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            root = ET.fromstring(z.read("xl/workbook.xml"))
        return "\n".join(el.get("name", "") for el in root.iter() if el.tag.endswith("}sheet"))
    return ""


def check_file(data: bytes, filename: str) -> str:
    """Kiểm tra tệp trước khi lưu; trả đuôi tệp viết thường."""
    if not data:
        raise TemplateError("Tệp rỗng")
    if len(data) > MAX_BYTES:
        raise TemplateError(f"Tệp lớn hơn {MAX_BYTES // (1024 * 1024)} MB")
    suffix = Path(filename).suffix.lower()
    if suffix not in SUFFIXES:
        raise TemplateError("Chỉ nhận .docx, .pdf, .xlsx, .doc")
    return suffix


def mime_of(suffix: str) -> str:
    return SUFFIXES[suffix] or {".docx": DOCX_MIME, ".xlsx": XLSX_MIME}.get(suffix, "")


def file_path(row: Template) -> Path:
    return TEMPLATE_DIR / f"{row.sha256}{Path(row.filename).suffix.lower()}"


def validate_basis(db: Session, node_ids: list[str]) -> list[str]:
    """Bỏ id trùng, giữ thứ tự; id không có trong `legal_node` -> TemplateError."""
    seen: list[str] = []
    for raw in node_ids:
        node_id = raw.strip()
        if not node_id or node_id in seen:
            continue
        if db.get(LegalNode, node_id) is None:
            raise TemplateError(f"Không tìm thấy điều luật {node_id}")
        seen.append(node_id)
    return seen


def basis_nodes(db: Session, node_ids: list[str]) -> list[dict]:
    """Căn cứ kèm `display` để giao diện hiện chip dễ đọc."""
    out = []
    for node_id in node_ids:
        node = db.get(LegalNode, node_id)
        out.append({
            "node_id": node_id,
            "display": (node.heading or (node.text or "")[:80]) if node else "",
        })
    return out


def to_dict(row: Template, db: Session | None = None, *, detail: bool = False) -> dict:
    basis = json.loads(row.legal_basis or "[]")
    out = {
        "id": row.id,
        "name": row.name,
        "kind": row.kind,
        "description": row.description,
        "legal_basis": basis,
        "filename": row.filename,
        "mime": row.mime,
        "size_bytes": row.size_bytes,
        "sha256": row.sha256,
        "text_preview": row.text_preview,
        "placeholders": json.loads(row.placeholders or "[]"),
        "version": row.version,
        "status": row.status,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }
    if detail and db is not None:
        out["legal_basis_nodes"] = basis_nodes(db, basis)
    return out


def get(db: Session, template_id: str) -> Template | None:
    return db.get(Template, template_id)


def by_sha(db: Session, sha256: str) -> Template | None:
    return db.scalars(select(Template).where(Template.sha256 == sha256)).first()


def write_file(row: Template, data: bytes) -> None:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    file_path(row).write_bytes(data)


def create(
    db: Session,
    data: bytes,
    filename: str,
    *,
    name: str,
    kind: str,
    description: str | None,
    legal_basis: list[str],
    created_by: str,
) -> Template:
    suffix = check_file(data, filename)
    if kind not in KINDS:
        raise TemplateError(f"Loại biểu mẫu không hợp lệ: {kind}")
    basis = validate_basis(db, legal_basis)
    try:
        text = extract_text(data, filename)
    except Exception as exc:  # noqa: BLE001 — tệp hỏng: báo người dùng, không lưu
        raise TemplateError(f"Không đọc được tệp: {exc}") from exc
    row = Template(
        id=uuid.uuid4().hex[:16],
        name=name.strip() or Path(filename).stem,
        kind=kind,
        description=(description or "").strip() or None,
        legal_basis=json.dumps(basis, ensure_ascii=False),
        filename=filename,
        mime=mime_of(suffix),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        text_preview=text[:PREVIEW_CHARS],
        placeholders=json.dumps(detect_placeholders(text), ensure_ascii=False),
        version=1,
        status="active",
        created_by=created_by,
    )
    db.add(row)
    db.commit()
    write_file(row, data)
    return row


def replace_file(db: Session, row: Template, data: bytes, filename: str) -> Template:
    """Bản mới của biểu mẫu: thay tệp, version + 1 (giữ tên/loại/căn cứ)."""
    suffix = check_file(data, filename)
    try:
        text = extract_text(data, filename)
    except Exception as exc:  # noqa: BLE001
        raise TemplateError(f"Không đọc được tệp: {exc}") from exc
    old = file_path(row)
    row.filename = filename
    row.mime = mime_of(suffix)
    row.size_bytes = len(data)
    row.sha256 = hashlib.sha256(data).hexdigest()
    row.text_preview = text[:PREVIEW_CHARS]
    row.placeholders = json.dumps(detect_placeholders(text), ensure_ascii=False)
    row.version += 1
    db.commit()
    write_file(row, data)
    if old != file_path(row):
        old.unlink(missing_ok=True)
    return row


def update(
    db: Session,
    row: Template,
    *,
    name: str | None = None,
    kind: str | None = None,
    description: str | None = None,
    legal_basis: list[str] | None = None,
    status: str | None = None,
) -> Template:
    if name is not None:
        row.name = name.strip() or row.name
    if kind is not None:
        if kind not in KINDS:
            raise TemplateError(f"Loại biểu mẫu không hợp lệ: {kind}")
        row.kind = kind
    if description is not None:
        row.description = description.strip() or None
    if legal_basis is not None:
        row.legal_basis = json.dumps(validate_basis(db, legal_basis), ensure_ascii=False)
    if status is not None:
        if status not in ("active", "archived"):
            raise TemplateError(f"Trạng thái không hợp lệ: {status}")
        row.status = status
    db.commit()
    return row


def remove(db: Session, row: Template, *, hard: bool = False) -> None:
    if not hard:
        row.status = "archived"
        db.commit()
        return
    path = file_path(row)
    db.delete(row)
    db.commit()
    path.unlink(missing_ok=True)


def search(db: Session, q: str | None, kind: str | None, status: str | None) -> list[Template]:
    """Lọc theo trạng thái/loại ở DB; `q` bỏ dấu tiếng Việt bằng `guard.normalize`."""
    stmt = select(Template).order_by(Template.created_at.desc())
    if kind:
        stmt = stmt.where(Template.kind == kind)
    if status:
        stmt = stmt.where(Template.status == status)
    rows = list(db.scalars(stmt).all())
    needle = normalize(q or "").strip()
    if not needle:
        return rows
    return [
        row for row in rows
        if needle in normalize(f"{row.name} {row.description or ''} {row.text_preview}")
    ]
