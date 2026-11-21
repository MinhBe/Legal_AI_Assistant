"""GenAI soạn văn bản: luồng mẫu đề xuất -> chỉnh -> chốt/khoá -> soạn (Minh 20/11/2026).

Phần lớn bằng code, không gọi AI:
- biến {{ten_bien}} trong nội dung; kiểu: text | date | money | number | long_text;
- kiểm khi khoá (lint): cú pháp biến, biến khai báo nhưng không dùng / dùng mà không khai báo,
  căn cứ pháp lý có trong kho và còn hiệu lực, không còn dấu [?] hay TODO;
- soạn: điền giá trị, kiểm kiểu từng biến, kèm danh sách căn cứ.
Chỉ trường long_text mới có nút "gợi ý câu chữ" bằng mô hình (suggest()); luật sư chốt.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import DocTemplate, DocTemplateVersion, LegalDocument, LegalNode

KINDS = ("hop_dong", "quyet_dinh", "don", "bien_ban", "thong_bao", "quy_che", "khac")
TYPES = ("text", "date", "money", "number", "long_text")
VAR = re.compile(r"\{\{\s*([^{}]*?)\s*\}\}")
NAME = re.compile(r"^[a-z][a-z0-9_]{0,40}$")


class DocgenError(ValueError):
    pass


def placeholders(body: str) -> list[str]:
    seen: list[str] = []
    for m in VAR.finditer(body):
        if m.group(1) not in seen:
            seen.append(m.group(1))
    return seen


def _guess_type(name: str) -> str:
    if name.startswith("ngay") or name.endswith("_ngay"):
        return "date"
    if any(k in name for k in ("luong", "tien", "muc_phat", "boi_thuong")):
        return "money"
    if name.startswith("so_") and not name.startswith("so_hieu"):
        return "number"
    if any(k in name for k in ("ly_do", "noi_dung", "mo_ta", "tinh_tiet")):
        return "long_text"
    return "text"


def default_fields(body: str, given: list[dict] | None = None) -> list[dict]:
    """Trường lấy từ biến trong nội dung; giữ nhãn/kiểu admin đã khai, biến mới thì đoán kiểu."""
    by = {f["name"]: f for f in (given or []) if isinstance(f, dict) and f.get("name")}
    out = []
    for n in placeholders(body):
        f = by.get(n, {})
        out.append({"name": n, "label": f.get("label") or n.replace("_", " ").capitalize(),
                    "type": f.get("type") if f.get("type") in TYPES else _guess_type(n),
                    "required": bool(f.get("required", True))})
    return out


def lint(db: Session, body: str, fields: list[dict], basis: list[str]) -> list[dict]:
    """Lỗi chặn khoá (level=error) và cảnh báo (level=warn). Không gọi AI."""
    issues: list[dict] = []
    used = placeholders(body)
    for n in used:
        if not NAME.match(n):
            issues.append({"level": "error", "code": "bad_name",
                           "message": f"Biến {{{{{n}}}}} sai cú pháp (chỉ chữ thường không dấu, số, _)"})
    declared = {f.get("name") for f in fields}
    for n in sorted(declared - set(used)):
        issues.append({"level": "warn", "code": "unused_field", "message": f"Trường {n} khai báo nhưng không dùng"})
    for n in used:
        if n not in declared:
            issues.append({"level": "error", "code": "undeclared", "message": f"Biến {n} chưa khai báo trường"})
    for f in fields:
        if f.get("type") not in TYPES:
            issues.append({"level": "error", "code": "bad_type", "message": f"Trường {f.get('name')}: kiểu không hợp lệ"})
    if "[?" in body or "TODO" in body:
        issues.append({"level": "error", "code": "unresolved", "message": "Còn chỗ đánh dấu [?] hoặc TODO"})
    if body.count("{{") != body.count("}}"):
        issues.append({"level": "error", "code": "braces", "message": "Số dấu {{ và }} không khớp"})
    if not basis:
        issues.append({"level": "warn", "code": "no_basis", "message": "Chưa có căn cứ pháp lý"})
    if basis:
        rows = db.execute(select(LegalNode.node_id, LegalDocument.status, LegalDocument.title)
                          .join(LegalDocument, LegalDocument.doc_id == LegalNode.doc_id)
                          .where(LegalNode.node_id.in_(basis))).all()
        found = {r[0]: r for r in rows}
        for nid in basis:
            r = found.get(nid)
            if r is None:
                issues.append({"level": "error", "code": "basis_missing", "message": f"Căn cứ {nid} không có trong kho"})
            elif r[1] == "expired":
                issues.append({"level": "error", "code": "basis_expired",
                               "message": f"Căn cứ {nid} thuộc văn bản hết hiệu lực ({r[2]})"})
            elif r[1] == "pending_review":
                issues.append({"level": "warn", "code": "basis_pending",
                               "message": f"Căn cứ {nid} thuộc văn bản đang chờ duyệt ({r[2]})"})
    return issues


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _latest(db: Session, tid: str) -> DocTemplateVersion | None:
    return db.execute(select(DocTemplateVersion).where(DocTemplateVersion.template_id == tid)
                      .order_by(DocTemplateVersion.version.desc()).limit(1)).scalar_one_or_none()


def _version(db: Session, tid: str, version: int) -> DocTemplateVersion | None:
    return db.execute(select(DocTemplateVersion).where(DocTemplateVersion.template_id == tid,
                                                       DocTemplateVersion.version == version)).scalar_one_or_none()


def propose(db: Session, *, name: str, kind: str, body: str, basis: list[str], note: str | None,
            author: str) -> DocTemplate:
    if kind not in KINDS:
        raise DocgenError(f"Loại văn bản không hợp lệ: {kind}")
    if not name.strip() or not body.strip():
        raise DocgenError("Thiếu tên hoặc nội dung")
    t = DocTemplate(id=uuid.uuid4().hex[:16], name=name.strip()[:200], kind=kind, status="proposed",
                    proposed_by=author)
    db.add(t)
    db.flush()
    db.add(DocTemplateVersion(template_id=t.id, version=1, body=body, fields=json.dumps(default_fields(body), ensure_ascii=False),
                              legal_basis=json.dumps(basis), note=note, author=author))
    db.commit()
    return t


def save_version(db: Session, t: DocTemplate, *, body: str, fields: list[dict] | None, basis: list[str],
                 note: str | None, author: str) -> DocTemplateVersion:
    """Admin chỉnh: bản mới nhất chưa khoá thì sửa tại chỗ; đã khoá thì tạo phiên bản mới."""
    if t.status == "archived":
        raise DocgenError("Mẫu đã lưu trữ")
    cur = _latest(db, t.id)
    f = json.dumps(default_fields(body, fields), ensure_ascii=False)
    if cur is not None and not cur.locked:
        cur.body, cur.fields, cur.legal_basis, cur.note, cur.author = body, f, json.dumps(basis), note, author
        v = cur
    else:
        v = DocTemplateVersion(template_id=t.id, version=(cur.version + 1 if cur else 1), body=body, fields=f,
                               legal_basis=json.dumps(basis), note=note, author=author)
        db.add(v)
    if t.status == "proposed":
        t.status = "draft"
    db.commit()
    return v


def lock(db: Session, t: DocTemplate, *, by: str) -> tuple[DocTemplateVersion | None, list[dict]]:
    v = _latest(db, t.id)
    if v is None:
        raise DocgenError("Mẫu chưa có nội dung")
    if v.locked:
        return v, []
    issues = lint(db, v.body, json.loads(v.fields), json.loads(v.legal_basis))
    if any(i["level"] == "error" for i in issues):
        return None, issues
    v.locked, v.locked_by, v.locked_at = True, by, _now()
    t.status, t.locked_version = "locked", v.version
    db.commit()
    return v, issues


def _check_value(f: dict, raw) -> tuple[str, str | None]:
    """(giá trị hiển thị, lỗi). Ngày dd/mm/yyyy hoặc yyyy-mm-dd; tiền ra dạng 1.234.000 đồng."""
    s = str(raw if raw is not None else "").strip()
    if not s:
        return "", ("Thiếu " + f["label"]) if f.get("required", True) else None
    t = f["type"]
    if t == "date":
        for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
            try:
                d = datetime.strptime(s, fmt)
                return d.strftime("%d/%m/%Y"), None
            except ValueError:
                continue
        return s, f"{f['label']}: ngày không hợp lệ (dd/mm/yyyy)"
    if t in ("money", "number"):
        digits = re.sub(r"[.\s,đ]|đồng|vnd|VND", "", s)
        if not digits.isdigit():
            return s, f"{f['label']}: phải là số"
        n = int(digits)
        return (f"{n:,}".replace(",", ".") + (" đồng" if t == "money" else "")), None
    return s, None


def generate(db: Session, t: DocTemplate, values: dict, version: int | None = None) -> dict:
    if t.locked_version is None:
        raise DocgenError("Mẫu chưa được chốt và khoá, chưa dùng để soạn được")
    v = _version(db, t.id, version or t.locked_version)
    if v is None or not v.locked:
        raise DocgenError("Chỉ soạn từ phiên bản đã khoá")
    fields = json.loads(v.fields)
    filled, errors = {}, []
    for f in fields:
        val, err = _check_value(f, values.get(f["name"]))
        filled[f["name"]] = val
        if err:
            errors.append(err)
    text = VAR.sub(lambda m: filled.get(m.group(1), m.group(0)), v.body)
    basis = json.loads(v.legal_basis)
    rows = db.execute(select(LegalNode.node_id, LegalNode.article_no, LegalNode.clause_no, LegalDocument.title,
                             LegalDocument.status)
                      .join(LegalDocument, LegalDocument.doc_id == LegalNode.doc_id)
                      .where(LegalNode.node_id.in_(basis))).all() if basis else []
    cites = [{"node_id": r[0], "display": f"Điều {r[1]}" + (f" khoản {r[2]}" if r[2] else "") + f" {r[3]}",
              "status": r[4]} for r in rows]
    return {"template_id": t.id, "version": v.version, "text": text, "errors": errors, "ok": not errors,
            "basis": cites, "as_of": _now().date().isoformat()}


def to_dict(db: Session, t: DocTemplate, *, detail: bool = False) -> dict:
    out = {"id": t.id, "name": t.name, "kind": t.kind, "status": t.status, "proposed_by": t.proposed_by,
           "locked_version": t.locked_version,
           "updated_at": t.updated_at.isoformat() if t.updated_at else None}
    if detail:
        vs = db.execute(select(DocTemplateVersion).where(DocTemplateVersion.template_id == t.id)
                        .order_by(DocTemplateVersion.version)).scalars().all()
        out["versions"] = [{"version": v.version, "body": v.body, "fields": json.loads(v.fields),
                            "legal_basis": json.loads(v.legal_basis), "note": v.note, "author": v.author,
                            "locked": v.locked, "locked_by": v.locked_by,
                            "locked_at": v.locked_at.isoformat() if v.locked_at else None} for v in vs]
    return out


def suggest(router, field_label: str, context: str) -> str:
    """Gợi ý câu chữ cho một trường dài (lý do, mô tả). Mức C, đám mây hoặc mô hình riêng; luật sư sửa."""
    from app.gateway.pii import mask
    from app.llm.context import cloud_first_scope, data_class_scope

    context = mask(context, mapping={}).text  # che tên, số trước khi gửi đi
    msgs = [{"role": "system", "content": "Bạn viết câu chữ văn bản pháp lý tiếng Việt, ngắn gọn, trang trọng, "
             "không bịa số hiệu, điều luật, số tiền hay ngày tháng. Chỉ trả về đoạn văn cho trường được hỏi."},
            {"role": "user", "content": f"Trường: {field_label}\nBối cảnh (đã che thông tin cá nhân):\n{context[:2000]}"}]
    with data_class_scope("C"), cloud_first_scope(True):
        return router.chat(msgs, task="draft", temperature=0.3).text.strip()
