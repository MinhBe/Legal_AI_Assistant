"""Nạp lại văn bản mở rộng kho đang ở chế độ "đoạn" nếu nay nhận được điều/khoản.

  python -m scripts.reparse_corpus_ext --dry-run
  python -m scripts.reparse_corpus_ext

Giữ nguyên trạng thái chờ duyệt. doc_meta và số hiệu/ngày hiệu lực/nguồn của
legal_document được lưu trước rồi ghi lại, vì ingest_upload xoá và tạo lại legal_document
(doc_meta xoá theo khoá ngoại ON DELETE CASCADE).
"""

from __future__ import annotations

import argparse

from loguru import logger
from sqlalchemy import text

from app.db.base import SessionLocal
from app.db.models import DocMeta, LegalDocument, UploadedFile
from app.ingestion.parser import assign_ids, parse_articles, validate
from app.upload import service
from app.upload.ingest import ingest_upload, tolerable

META_COLS = ("domain", "number", "effective_from", "effective_to", "replaced_by",
             "consolidates", "source_url")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    db = SessionLocal()
    try:
        metas = db.query(DocMeta).all()
        for m in metas:
            modes = db.execute(text("SELECT count(article_no) FROM legal_node WHERE doc_id = :d"),
                               {"d": m.doc_id}).scalar()
            row = db.query(UploadedFile).filter(UploadedFile.doc_id == m.doc_id).one()
            body = service.full_text(db, row)
            arts = parse_articles(body)
            assign_ids(m.doc_id, arts)
            issues = validate(arts, body)
            ok = len(arts) >= 1 and tolerable(issues, len(arts))
            logger.info("{} {}: {} điều, {} cảnh báo, có số điều={}, sẽ nạp lại={}", m.number,
                        row.filename, len(arts), len(issues), bool(modes), ok and not modes)
            if args.dry_run or modes or not ok:
                continue
            saved = {c: getattr(m, c) for c in META_COLS}
            doc = db.get(LegalDocument, m.doc_id)
            doc_saved = {"number": doc.number, "effective_date": doc.effective_date,
                         "source_url": doc.source_url, "status": doc.status}
            res = ingest_upload(db, doc_id=m.doc_id, title=doc.title, text=body,
                                filename=row.filename)
            doc = db.get(LegalDocument, m.doc_id)
            for k, v in doc_saved.items():
                setattr(doc, k, v)
            db.merge(DocMeta(doc_id=m.doc_id, **saved))
            row.parse_mode, row.n_nodes, row.n_refs = res["parse_mode"], res["n_nodes"], res["n_refs"]
            db.commit()
            logger.info("-> {}: {} node, chế độ {}", m.number, res["n_nodes"], res["parse_mode"])
    finally:
        db.close()


if __name__ == "__main__":
    main()
