"""Hồ sơ intake đã làm mờ -> phân tích v2.1 (tình tiết, câu hỏi pháp lý, điều luật, gợi ý).

Mức dữ liệu theo bản đã lưu: "C" (mọi đoạn nhạy cảm đã làm mờ) đi theo kế hoạch mức C của router;
"B" (khách giữ nguyên ít nhất một đoạn) chỉ mô hình trong máy. Kết quả ghi ra
data/intake/analysis/<id>.json; status của hồ sơ thành "analysed" hoặc "failed".
"""

from __future__ import annotations

import json
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from app.db.base import SessionLocal
from app.db.models import IntakeRecord, LegalDocument
from app.llm.context import cloud_first_scope, data_class_scope
from app.llm.router import get_router
from app.problems import spoken_v2

OUT = Path("data/intake/analysis")


def corpus_docs(db) -> list[str]:
    rows = db.execute(select(LegalDocument.title, LegalDocument.number, LegalDocument.status)).all()
    out = []
    for title, number, status in rows:
        if title.lower().startswith(("án lệ", "an_le")):
            continue
        tag = "" if status == "active" else (", hết hiệu lực" if status == "expired" else ", chờ duyệt")
        out.append(f"{title} ({number or 'không số'}{tag})")
    return out


def run(intake_id: str) -> None:
    db = SessionLocal()
    try:
        row = db.get(IntakeRecord, intake_id)
        if row is None:
            return
        docs = corpus_docs(db)
        router = get_router()

        def call(messages):
            # mức C (đã che hết): đám mây trước, không chiếm máy; mức B: router chỉ cho mô hình trong máy
            with data_class_scope(row.data_class), cloud_first_scope(row.data_class == "C"):
                return router.chat(messages, task="route", temperature=0.2).text

        try:
            result = spoken_v2.run(call, {"A": row.text}, docs)
            result["audit"] = spoken_v2.audit(result, row.text, docs)
            result["enforced"] = spoken_v2.enforce(result, docs)
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / f"{intake_id}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                                   encoding="utf-8")
            row.status = "analysed" if result["units"] else "failed"
        except Exception as exc:  # job nền không được ném ra ngoài
            logger.warning("phân tích intake {} lỗi: {}", intake_id, exc)
            row.status = "failed"
        db.commit()
    finally:
        db.close()


def load(intake_id: str) -> dict | None:
    p = OUT / f"{intake_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
