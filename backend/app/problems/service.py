"""Lưu, đọc và duyệt "bài toán" (AU2); dựng hộp gợi ý cho câu trả lời (PR1).

Bài toán mới luôn ở trạng thái `goi_y`: chỉ là ý tưởng cho mô hình. Chỉ khi luật sư
PATCH sang `da_duyet` mới có tên người duyệt và mới được hiện thành "tham khảo thêm"
trong chat; không bao giờ vào prompt hay trích dẫn.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app.db.models import CaseProblem, UploadedFile
from app.llm.router import get_router
from app.problems import link, extract

_JSON_FIELDS = (
    "options",
    "cited_articles",
    "uncertain_points",
    "linked_articles",
    "linked_precedents",
)
_STATUSES = ("goi_y", "da_duyet", "bac_bo")


def _ts(seconds: float | None) -> str:
    s = max(0, int(seconds or 0))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _span(start: float | None, end: float | None) -> str:
    return f"{_ts(start)}–{_ts(end)}"


def _text(item: dict) -> str:
    return " ".join(
        str(item.get(key) or "") for key in ("title", "facts", "legal_question")
    ).strip()


def save(
    db: Session,
    items: list[dict],
    *,
    source_kind: str,
    upload_id: str | None = None,
    processed_by: str = "local",
) -> list[CaseProblem]:
    """Ghi các bài toán đã rút, kèm điều luật/án lệ nối bằng code."""
    out: list[CaseProblem] = []
    for item in items:
        if not all(str(item.get(k) or "").strip() for k in ("title", "facts", "legal_question")):
            continue
        problem = CaseProblem(
            id=uuid.uuid4().hex[:16],
            source_kind=source_kind,
            upload_id=upload_id,
            source_ts=(
                _span(item.get("start_ts"), item.get("end_ts"))
                if source_kind == "audio"
                else None
            ),
            title=str(item.get("title") or "").strip(),
            facts=str(item.get("facts") or "").strip(),
            legal_question=str(item.get("legal_question") or "").strip(),
            suggested_approach=str(item.get("suggested_approach") or "").strip(),
            options=json.dumps(item.get("options") or [], ensure_ascii=False),
            cited_articles=json.dumps(item.get("cited_articles") or [], ensure_ascii=False),
            uncertain_points=json.dumps(
                item.get("uncertain_points") or [], ensure_ascii=False
            ),
            linked_articles=json.dumps(
                link.link_articles(
                    db,
                    f"{item.get('facts') or ''} {item.get('legal_question') or ''}".strip(),
                ),
                ensure_ascii=False,
            ),
            linked_precedents=json.dumps(
                link.link_precedents(db, _text(item)), ensure_ascii=False
            ),
            processed_by=processed_by,
        )
        db.add(problem)
        out.append(problem)
    if out:
        db.commit()
    return out


def extract_note(
    db: Session,
    text: str,
    *,
    allow_dahl: bool = False,
    mapping: dict[str, str] | None = None,
    router=None,
) -> list[CaseProblem]:
    """Ghi chú nhóm -> bài toán (một lời gọi mô hình cho cả ghi chú)."""
    items = extract.extract(
        router or get_router(), text, allow_dahl=allow_dahl, mapping=mapping
    )
    return save(
        db,
        items,
        source_kind="note",
        processed_by="dahl" if allow_dahl else "local",
    )


def to_dict(problem: CaseProblem) -> dict:
    data = {
        "id": problem.id,
        "source_kind": problem.source_kind,
        "upload_id": problem.upload_id,
        "source_ts": problem.source_ts,
        "title": problem.title,
        "facts": problem.facts,
        "legal_question": problem.legal_question,
        "suggested_approach": problem.suggested_approach,
        "processed_by": problem.processed_by,
        "status": problem.status,
        "lawyer_analysis": problem.lawyer_analysis,
        "lawyer_verdict": problem.lawyer_verdict,
        "approved_by": problem.approved_by,
        "approved_at": problem.approved_at.isoformat() if problem.approved_at else None,
        "created_at": problem.created_at.isoformat() if problem.created_at else None,
        "filename": None,
    }
    for field in _JSON_FIELDS:
        try:
            data[field] = json.loads(getattr(problem, field) or "[]")
        except ValueError:
            data[field] = []
    session = object_session(problem)
    if session is not None and problem.upload_id:
        uploaded = session.get(UploadedFile, problem.upload_id)
        data["filename"] = uploaded.filename if uploaded else None
    return data


def list_problems(db: Session, status: str | None = None) -> list[dict]:
    stmt = select(CaseProblem).order_by(CaseProblem.created_at.desc())
    if status:
        stmt = stmt.where(CaseProblem.status == status)
    return [to_dict(p) for p in db.scalars(stmt).all()]


def get(db: Session, problem_id: str) -> CaseProblem | None:
    return db.get(CaseProblem, problem_id)


def review(db: Session, problem: CaseProblem, payload: dict, user: dict) -> CaseProblem:
    """Luật sư duyệt/bác bỏ; `da_duyet` gắn tên và thời điểm người duyệt."""
    for field in ("lawyer_analysis", "lawyer_verdict"):
        if field in payload:
            setattr(problem, field, payload[field])
    status = payload.get("status")
    if status in _STATUSES:
        problem.status = status
        if status == "da_duyet":
            who = user.get("username") or user.get("role") or ""
            problem.approved_by = who[:32]
            problem.approved_at = datetime.now(UTC)
        elif status == "bac_bo":
            problem.approved_by = None
            problem.approved_at = None
    db.commit()
    return problem


def answer_hints(db: Session, question: str) -> dict:
    """Hộp "tham khảo thêm" cho một câu trả lời: ≤2 án lệ, ≤2 bài toán đã duyệt."""
    precedents = link.link_precedents(db, question, top_k=2)
    problems = link.link_problems(db, question, top_k=2)
    return {
        "precedents": precedents,
        "problems": [
            {"id": p["id"], "title": p["title"], "approved_by": p["approved_by"]}
            for p in problems
        ],
    }
