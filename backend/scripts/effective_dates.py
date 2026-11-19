"""Ngày hiệu lực lấy từ chính điều khoản hiệu lực của văn bản (code đọc, không để mô hình suy ra).

    python -m scripts.effective_dates            # in kết quả, không ghi
    python -m scripts.effective_dates --write    # ghi doc_meta.effective_from + legal_document.effective_date

Trang Công báo có khi ghi ngày ban hành ở ô "hiệu lực". Điều khoản thi hành của văn bản ghi
"có hiệu lực (thi hành) (kể) từ ngày dd tháng mm năm yyyy". Chỉ văn bản đang chờ duyệt mới được
sửa; văn bản không có câu đó hoặc có nhiều ngày (hiệu lực theo giai đoạn) thì chỉ báo, không ghi.
"""

from __future__ import annotations

import argparse
import re
from datetime import date

from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import DocMeta, LegalDocument, LegalNode

_CLAUSE = re.compile(
    r"có hiệu lực(?: thi hành)?(?: kể)? từ ngày\s+(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
    re.IGNORECASE,
)


def clause_dates(text: str) -> list[date]:
    out = []
    for d, m, y in _CLAUSE.findall(text):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            continue
    return out


def main_date(texts: list[str]) -> tuple[date | None, str]:
    """(ngày, ghi chú). Đọc từ các điều cuối (điều khoản thi hành nằm cuối văn bản)."""
    found: list[date] = []
    for t in texts:
        found += clause_dates(t)
    uniq = sorted(set(found))
    if not uniq:
        return None, "không thấy câu 'có hiệu lực từ ngày'"
    if len(uniq) > 1:
        return None, "nhiều ngày hiệu lực (theo giai đoạn): " + ", ".join(d.isoformat() for d in uniq)
    return uniq[0], ""


def run(write: bool) -> None:
    db = SessionLocal()
    try:
        rows = db.execute(select(LegalDocument, DocMeta).join(DocMeta, DocMeta.doc_id == LegalDocument.doc_id)
                          .where(LegalDocument.status == "pending_review")).all()
        for doc, meta in rows:
            last = db.execute(select(LegalNode.text).where(LegalNode.doc_id == doc.doc_id)
                              .order_by(LegalNode.seq.desc()).limit(40)).scalars().all()
            when, note = main_date(last)
            old = meta.effective_from
            mark = "=" if when == old else ("→" if when else "?")
            print(f"{mark} {meta.number or doc.doc_id}: trang {old} | điều khoản {when} {note}")
            if write and when and when != old:
                note_old = f"ngày trên trang Công báo: {old}" if old else ""
                meta.effective_from = when
                meta.consolidates = "; ".join(x for x in (meta.consolidates, note_old) if x) or None
                doc.effective_date = when
        if write:
            db.commit()
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    run(ap.parse_args().write)


if __name__ == "__main__":
    main()
