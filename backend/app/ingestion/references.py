"""Trích dẫn chiếu nội văn bản: "khoản 2 Điều 35", "điểm d khoản 1 Điều 35 của Bộ luật Lao động".

Khó nhất không phải bắt được con số mà là biết dẫn chiếu trỏ sang văn bản nào.
Nghị định 145 có tới Điều 115, nên "theo khoản 3 Điều 12" để trống tên văn bản
vẫn khớp được trong chính nó, trong khi nghĩa thật là Điều 12 Bộ luật Lao động.
Vì vậy ngữ cảnh văn bản được kế thừa: lần nhắc tên rõ ràng gần nhất phía trước
thắng, rồi tới ngữ cảnh của Điều cha, cuối cùng mới mặc định là văn bản nguồn.

Văn bản đích nhận ra được bằng tên ("Bộ luật Lao động 2012") hoặc số hiệu
("Nghị định 145/2020/NĐ-CP", "NĐ 145/2020", "Nghị định 145"), đối chiếu với bản đồ
``known_docs`` (khoá đã bỏ dấu -> doc_id) dựng từ ``legal_document``.
"""

from __future__ import annotations

import re

# điểm a | khoản 1 | Điều 35 — ba phần đầu đều có thể vắng trừ "Điều"
RE_REF = re.compile(
    r"(?:điểm\s+([a-zđ])\s+)?"
    r"(?:khoản\s+(\d{1,2})\s+)?"
    r"Điều\s+(\d{1,3})\b",
    re.IGNORECASE,
)

_DOC_KIND = r"(Bộ\s*luật(?:\s+Lao\s*động)?|Nghị\s*định|Thông\s*tư|Luật|BLLĐ|NĐ)"
# tên/năm/số hiệu đi sau loại văn bản: "này", "Lao động 2012", "2012", "145/2020/NĐ-CP"
_DOC_REST = (
    r"(?:\s+("
    r"này|Lao\s*động(?:\s+(?:năm\s+)?\d{4})?|năm\s+\d{4}|\d{4}|[\d][\w/\-]*"
    r"))?"
)
_DOC = _DOC_KIND + r"(?:\s+số)?" + _DOC_REST

# tên/số hiệu văn bản đi ngay sau dẫn chiếu: "của Bộ luật này", "của Bộ luật Lao động"
RE_DOC_AFTER = re.compile(r"^[\s,]*(?:của\s+|tại\s+)?" + _DOC, re.IGNORECASE)

# tên/số hiệu văn bản nhắc ở bất kỳ đâu trong câu, dùng làm ngữ cảnh kế thừa
RE_DOC_ANY = re.compile(_DOC, re.IGNORECASE)

#: tên gọi -> doc_id. "Bộ luật Lao động" trỏ bản đang có hiệu lực.
NAMED_DOCS = {"bo luat lao dong": "blld2019", "blld": "blld2019"}


def _flat(s: str) -> str:
    """Bỏ dấu thô để so khớp tên văn bản, đủ dùng cho vài tên cố định."""
    out = s.lower()
    for a, b in (
        ("àáảãạăằắẳẵặâầấẩẫậ", "a"), ("èéẻẽẹêềếểễệ", "e"),
        ("ìíỉĩị", "i"), ("òóỏõọôồốổỗộơờớởỡợ", "o"),
        ("ùúủũụưừứửữự", "u"), ("ỳýỷỹỵ", "y"), ("đ", "d"),
    ):
        for ch in a:
            out = out.replace(ch, b)
    return re.sub(r"\s+", " ", out).strip()


def known_docs_from_db(db) -> dict[str, str]:
    """Số hiệu + tên văn bản (đã bỏ dấu) -> doc_id; bỏ qua văn bản tải lên."""
    from sqlalchemy import or_, select

    from app.db.models import LegalDocument

    rows = db.execute(
        select(LegalDocument.doc_id, LegalDocument.number, LegalDocument.title).where(
            or_(LegalDocument.doc_type.is_(None), LegalDocument.doc_type != "upload")
        )
    ).all()
    out: dict[str, str] = {}
    for doc_id, number, title in rows:
        if number:
            out[_flat(number)] = doc_id
        if title:
            out[_flat(title)] = doc_id
    return out


def _by_number(num: str, index: dict[str, str]) -> str | None:
    """Khớp số hiệu theo tiền tố dài dần: "145/2020/nđ-cp" -> "145/2020" -> "145"."""
    if doc := index.get(num):
        return doc
    parts = num.split("/")
    for n in range(len(parts), 0, -1):
        pref = "/".join(parts[:n])
        hits = {
            v for k, v in index.items()
            if k == pref or k.startswith(pref + "/")
        }
        if len(hits) == 1:
            return hits.pop()
    return None


def _year_doc(year: str, index: dict[str, str]) -> str | None:
    """Bộ luật Lao động kèm năm -> đúng bản của năm đó."""
    for key in (f"bo luat lao dong {year}", f"blld{year}"):
        if doc := index.get(key):
            return doc
    if not index:  # không có bản đồ: chỉ biết hai bản trong kho
        return f"blld{year}" if year in {"2012", "2019"} else None
    cand = f"blld{year}"
    return cand if cand in index.values() else None


def _resolve_doc(
    kind: str, rest: str | None, src_doc: str, index: dict[str, str]
) -> str | None:
    """Cụm văn bản trong câu -> doc_id."""
    flat_rest = _flat(rest) if rest else ""
    if flat_rest == "nay":
        return src_doc
    full = _flat(f"{kind} {rest}" if rest else kind)

    if flat_rest and (m := re.fullmatch(r"(?:nam\s+)?(\d{4})", flat_rest)):
        if "lao dong" in full or _flat(kind) == "blld":
            return _year_doc(m.group(1), index)

    if flat_rest and flat_rest[0].isdigit():  # số hiệu văn bản
        return _by_number(flat_rest, index)

    for key, doc in NAMED_DOCS.items():
        if key in full:
            # Bộ luật 2012 tự nhắc tên mình thì vẫn là chính nó
            return src_doc if src_doc == "blld2012" else doc
    return index.get(full)


def _node_id(doc: str, art: int, clause: int | None, point: str | None) -> str:
    nid = f"{doc}-d{art}"
    if clause is not None:
        nid += f"-k{clause}"
        if point:
            nid += f"-{point}"
    return nid


def extract_refs(
    text: str,
    src_doc: str,
    *,
    article_context: str | None = None,
    known_docs: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """Trả về [(node_id đích, đoạn trích)] — chưa kiểm tra node có thật hay không.

    ``article_context`` là toàn văn của Điều cha, dùng khi bản thân đoạn text
    không nhắc tên văn bản nào. ``known_docs`` là bản đồ khoá đã bỏ dấu -> doc_id
    (xem :func:`known_docs_from_db`) để nhận ra văn bản theo số hiệu.
    """
    if not text:
        return []
    index = {_flat(k): v for k, v in (known_docs or {}).items()}

    # ngữ cảnh dự phòng từ Điều cha
    inherited: str | None = None
    if article_context:
        for m in RE_DOC_ANY.finditer(article_context):
            doc = _resolve_doc(m.group(1), m.group(2), src_doc, index)
            if doc and doc != src_doc:
                inherited = doc
                break

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    last_explicit: str | None = None

    for m in RE_REF.finditer(text):
        point, clause, art = m.group(1), m.group(2), m.group(3)

        tail = text[m.end():m.end() + 70]
        if dm := RE_DOC_AFTER.match(tail):
            doc = _resolve_doc(dm.group(1), dm.group(2), src_doc, index)
            if doc:
                last_explicit = doc
        doc = last_explicit or inherited or src_doc

        nid = _node_id(
            doc, int(art),
            int(clause) if clause else None,
            point.lower() if point else None,
        )
        if nid in seen:
            continue
        seen.add(nid)
        out.append((nid, m.group(0).strip()))

    return out
