"""Các endpoint HTTP."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Body, Depends, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import prompts
from app.agent import record, risk
from app.agent.pipeline import run_chat
from app.gateway.pii import mask
from app.config import get_settings
from app.obs import metrics
from app.db.base import SessionLocal, get_db
from app.db.models import LegalDocument, LegalNode, ReviewCase, Thread
from app.graph.builder import build_graph
from app.llm.router import get_router
from app.pv.library import LAYERS, load_library
from app.pv.chat import run_pv_chat
from app.pv.graph import build_pv_graph
from app.review import autonomy, sla, traps
from app.review import service as review
from app.sse import sse

router = APIRouter()


# ---------- Health ----------
@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        n_docs = db.scalar(select(func.count()).select_from(LegalDocument)) or 0
        n_nodes = db.scalar(select(func.count()).select_from(LegalNode)) or 0
        db_ok = True
    except Exception:  # noqa: BLE001
        n_docs = n_nodes = 0
        db_ok = False
    return {
        "status": "ok",
        "db": db_ok,
        "documents": n_docs,
        "nodes": n_nodes,
        "data_loaded": n_nodes > 0,
        "llm": get_router().available_providers(),
    }


# ---------- Tra cứu điều luật ----------
@router.get("/api/law/verify")
def law_verify_route(as_of: str | None = None, db: Session = Depends(get_db)):
    from datetime import date as _date

    from app.amend.cascade import corpus_freshness, needs_verification

    day = _date.fromisoformat(as_of) if as_of else _date.today()
    return {
        "as_of": day.isoformat(),
        "items": needs_verification(db, day),
        "freshness": corpus_freshness(db, day),
    }


# đặt sau /api/law/verify để "verify" không bị nuốt bởi tham số đường dẫn
@router.get("/api/law/{node_id}")
def get_law(node_id: str, db: Session = Depends(get_db)):
    node = db.get(LegalNode, node_id)
    if not node:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy node {node_id}")
    return {
        "node_id": node.node_id,
        "doc_id": node.doc_id,
        "level": node.level,
        "heading": node.heading,
        "text": node.text,
        "effective_from": node.effective_from,
        "effective_to": node.effective_to,
    }


@router.get("/api/documents")
def list_documents(db: Session = Depends(get_db)):
    docs = db.scalars(select(LegalDocument)).all()
    return [
        {"doc_id": d.doc_id, "title": d.title, "doc_type": d.doc_type, "status": d.status}
        for d in docs
    ]


# ---------- Tìm kiếm (M2 sẽ hoàn thiện) ----------
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


@router.post("/api/search")
def search(req: SearchRequest, db: Session = Depends(get_db)):
    from app.rag.search import search_nodes

    hits = search_nodes(db, req.query, top_k=req.top_k)
    return {"query": req.query, "hits": hits}


# ---------- Máy tính theo phiên bản luật (I2) ----------
_CALC_SPECS = {
    "notice": ("notice_days", ("contract_type", "employer_side", "term_months"), ()),
    "service-years": ("service_years", ("start", "end", "unemployment_insured_months"), ("start", "end")),
    "severance": ("severance", ("avg_salary_6m", "years"), ()),
    "job-loss": ("job_loss", ("avg_salary_6m", "years"), ()),
    "unlawful-dismissal": (
        "unlawful_dismissal",
        ("monthly_salary", "days_not_working", "notice_days_missing", "daily_salary"),
        (),
    ),
    "limitation": ("limitation", ("discovered_on", "dispute"), ("discovered_on",)),
}
_CALC_REQUIRED = {
    "notice": ("contract_type", "employer_side"),
    "service-years": ("start", "end"),
    "severance": ("avg_salary_6m", "years"),
    "job-loss": ("avg_salary_6m", "years"),
    "unlawful-dismissal": ("monthly_salary", "days_not_working"),
    "limitation": ("discovered_on",),
}


@router.post("/api/calc/{kind}")
def calc_route(
    kind: str,
    body: dict[str, Any] = Body(default_factory=dict),
    db: Session = Depends(get_db),
):
    from datetime import date as _date

    from app.amend.timeframe import resolve
    from app.calc import labor

    spec = _CALC_SPECS.get(kind)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Không có máy tính {kind}")
    fn_name, names, date_fields = spec

    payload = dict(body or {})
    raw_event = payload.pop("event_date", None)
    try:
        event = _date.fromisoformat(raw_event) if raw_event else _date.today()
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422, detail="event_date không hợp lệ (cần YYYY-MM-DD)"
        ) from None

    missing = [n for n in _CALC_REQUIRED[kind] if payload.get(n) is None]
    if missing:
        raise HTTPException(status_code=422, detail=f"thiếu {', '.join(missing)}")

    kwargs: dict[str, Any] = {}
    for name in names:
        if name not in payload or payload[name] is None:
            continue
        value = payload[name]
        if name in date_fields:
            try:
                value = _date.fromisoformat(str(value))
            except ValueError:
                raise HTTPException(
                    status_code=422, detail=f"{name} không hợp lệ (cần YYYY-MM-DD)"
                ) from None
        kwargs[name] = value

    try:
        result = getattr(labor, fn_name)(**kwargs, event_date=event, db=db)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    result["timeframe_version"] = resolve(db, event, _date.today())["applicable"]
    return result


# ---------- Hiệu lực theo thời gian + sửa đổi (M4) ----------
@router.get("/api/law_as_of")
def law_as_of_route(date: str, topic: str | None = None, db: Session = Depends(get_db)):
    from datetime import date as _date

    from app.amend.store import law_as_of

    rows = law_as_of(db, _date.fromisoformat(date), topic=topic)
    return {"date": date, "topic": topic, "count": len(rows), "nodes": rows}


@router.get("/api/node/{node_id}/history")
def node_history_route(node_id: str, db: Session = Depends(get_db)):
    from app.amend.store import node_history

    return {"node_id": node_id, "history": node_history(db, node_id)}


class DiffRequest(BaseModel):
    old_doc_id: str
    new_doc_id: str
    write: bool = False


@router.post("/api/admin/diff")
def diff_route(req: DiffRequest, db: Session = Depends(get_db)):
    from app.amend.store import diff_documents

    diffs = diff_documents(db, req.old_doc_id, req.new_doc_id, write=req.write)
    changed = [d for d in diffs if d["change_type"] != "unchanged"]
    return {"total": len(diffs), "changed": len(changed), "diffs": changed[:200]}


# ---------- Soạn thảo văn bản NĐ30 (M5) ----------
class DraftRequest(BaseModel):
    doc_type: str = "quyet_dinh"
    org_name: str = ""
    org_parent: str | None = None
    number: str | None = None
    place: str = "Hà Nội"
    subject: str = ""
    bases: list[str] = []
    body: str = ""
    signer_title: str = "GIÁM ĐỐC"
    signer_name: str = ""
    recipients: list[str] = ["Như trên", "Lưu: VT."]
    auto_bases: bool = True


def _suggest_bases(db: Session) -> list[str]:
    """Gợi ý 'Căn cứ' từ các văn bản còn hiệu lực trong kho."""
    from app.db.models import LegalDocument

    docs = db.scalars(
        select(LegalDocument).where(LegalDocument.status == "active")
    ).all()
    out = []
    for d in docs:
        if d.doc_type == "luat":
            out.append(f"{d.title} số {d.number}")
        elif d.doc_type:
            out.append(f"{d.title}")
    return out


def _to_input(req: DraftRequest, db: Session):
    from app.draft.nd30 import DraftInput

    bases = list(req.bases)
    if req.auto_bases and not bases:
        bases = _suggest_bases(db)
    return DraftInput(
        doc_type=req.doc_type, org_name=req.org_name, org_parent=req.org_parent,
        number=req.number, place=req.place, subject=req.subject, bases=bases,
        body=req.body, signer_title=req.signer_title, signer_name=req.signer_name,
        recipients=req.recipients,
    )


@router.post("/api/draft/preview")
def draft_preview(req: DraftRequest, db: Session = Depends(get_db)):
    from app.draft.nd30 import format_check, render_text

    d = _to_input(req, db)
    return {"text": render_text(d), "issues": format_check(d), "bases": d.bases}


@router.post("/api/draft/export")
def draft_export(req: DraftRequest, db: Session = Depends(get_db)):
    from app.draft.nd30 import render_docx

    data = render_docx(_to_input(req, db))
    from fastapi.responses import Response

    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="van-ban.docx"'},
    )


# ---------- Tổng hợp án lệ (M6b) ----------
class PrecedentRequest(BaseModel):
    query: str
    top_k: int = 4


@router.post("/api/precedent")
def precedent_route(req: PrecedentRequest):
    from app.agent.precedent import synthesize

    return synthesize(req.query, top_k=req.top_k)


# ---------- Báo cáo nhiều văn bản (M6) ----------
class ReportRequest(BaseModel):
    topic: str
    top_k: int = 15


@router.post("/api/report")
def report_route(req: ReportRequest):
    from app.report.multi_doc import build_report

    return build_report(req.topic, top_k=req.top_k)


@router.post("/api/report/export")
def report_export_route(req: ReportRequest):
    from fastapi.responses import Response

    from app.report.multi_doc import build_report, report_to_docx

    data = report_to_docx(build_report(req.topic, top_k=req.top_k))
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": 'attachment; filename="bao-cao.docx"'},
    )


# ---------- Chat (SSE) ----------
class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    thread_id: str | None = None
    history: list[ChatMessage] = []
    mode: Literal["law", "pv"] = "law"  # "pv": chế độ ẩn, nguồn là bộ câu hỏi phỏng vấn
    use_uploads: bool = False  # dùng văn bản đã duyệt; chạy mức A, chỉ trong máy


@router.post("/api/chat")
def chat(req: ChatRequest):
    history = [{"role": m.role, "content": m.content} for m in req.history]

    def gen():
        thread_id = req.thread_id or uuid.uuid4().hex
        yield sse("start", {"thread_id": thread_id})
        ctx = None
        events: list[tuple[str, object]] = []
        failed = False
        try:
            ctx = metrics.start_request(
                "chat", mode=req.mode, prompt_version=prompts.active_version("qa_answer"),
                search_mode=get_settings().search_mode, question=req.message,
            )
            for event, data in metrics.traced(
                run_chat(
                    req.message, history, req.mode,
                    **{"use_uploads": True} if req.use_uploads else {},
                ),
                ctx,
            ):
                events.append((event, data))
                yield sse(event, data)
        except Exception as exc:  # noqa: BLE001
            failed = True
            yield sse("error", {"message": str(exc)})
        # Hồ sơ câu trả lời (T7): ghi sau khi luồng xong, hỏng thì bỏ qua, không làm gãy chat.
        if ctx is None or failed:
            return
        rec_id = None
        try:
            rec = record.build(ctx, events, thread_id)
            if rec:
                db = SessionLocal()
                try:
                    rec_id = record.save(db, rec)
                finally:
                    db.close()
                yield sse("record", {"id": rec_id})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Không ghi được hồ sơ câu trả lời: {}", exc)
        # Rủi ro (R1): chấm bằng quy tắc; vào hàng đợi thì tạo ca cho luật sư.
        # Chỉ chấm câu trả lời pháp lý (có timeframe) và câu ngoài kho; chặn chèn lệnh /
        # lạc đề thì không có gì để luật sư duyệt.
        kinds = {e for e, _ in events}
        out_of_corpus = any(e == "done" and isinstance(d, dict) and d.get("category") == "out_of_corpus"
                            for e, d in events)
        if "timeframe" not in kinds and not out_of_corpus:
            return
        try:
            r = risk.score(req.message, events)
            question = ctx.get("question") or req.message
            on_duty = True
            try:
                db = SessionLocal()
                try:
                    ct = autonomy.case_type(question)
                    r["case_type"] = ct
                    r["autonomy_level"] = autonomy.get_level(db, ct)
                    on_duty = sla.is_on_duty(db)
                finally:
                    db.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Không đọc được mức tự chủ: {}", exc)
            if r["queue"]:
                try:
                    r["case_id"] = _open_review_case(rec_id, question, r, thread_id)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Không tạo được ca duyệt: {}", exc)
                # Mức 1: gửi khách ngay nhưng phải mang nhãn "chưa xác nhận" (design §9.4).
                r["unconfirmed"] = r.get("autonomy_level") == 1
                if not on_duty:
                    r["no_lawyer"] = True
            yield sse("risk", r)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Không chấm được điểm rủi ro: {}", exc)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


# ---------- Hồ sơ câu trả lời (T7) ----------
@router.get("/api/answers/{rec_id}")
def get_answer_route(rec_id: str, db: Session = Depends(get_db)):
    rec = record.get(db, rec_id)
    if not rec:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy hồ sơ {rec_id}")
    return rec


@router.get("/api/answers")
def list_answers_route(limit: int = 50, db: Session = Depends(get_db)):
    return record.list_recent(db, limit)


# ---------- Hàng đợi duyệt theo rủi ro (R1) ----------
def _review_case_row(c: ReviewCase) -> dict:
    return review.case_row(c)


def _open_review_case(answer_id, question, r, thread_id) -> str:
    db = SessionLocal()
    try:
        case_id = uuid.uuid4().hex[:16]
        db.add(ReviewCase(
            id=case_id, answer_id=answer_id, question=question,
            risk_score=str(r["score"]), reasons=json.dumps(r["reasons"], ensure_ascii=False),
            status="pending", source="auto", thread_id=thread_id,
            case_type=autonomy.case_type(question),
        ))
        db.commit()
        # Cứ 20 ca tự động thì trộn một ca bẫy vào hàng đợi (design §15.6).
        try:
            traps.maybe_insert_trap(db)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Không chèn được ca bẫy: {}", exc)
        return case_id
    finally:
        db.close()


@router.get("/api/review/cases")
def list_review_cases(status: str = "pending", db: Session = Depends(get_db)):
    """`status="all"` trả mọi ca; mặc định chỉ ca chờ duyệt."""
    query = select(ReviewCase).order_by(ReviewCase.created_at.desc())
    if status != "all":
        query = query.where(ReviewCase.status == status)
    return [_review_case_row(c) for c in db.scalars(query).all()]


@router.get("/api/review/cases/{case_id}")
def get_review_case(case_id: str, db: Session = Depends(get_db)):
    case = db.get(ReviewCase, case_id)
    if not case:
        raise HTTPException(status_code=404, detail=f"Không tìm thấy ca {case_id}")
    answer = record.get(db, case.answer_id) if case.answer_id else None
    return {**_review_case_row(case), "answer": answer}


# ---------- Bàn duyệt luật sư: gói ca + bốn hành động (R2, design §9.2–9.3) ----------
class ReviewActRequest(BaseModel):
    action: Literal["approve", "light_edit", "heavy_edit", "reject"]
    text: str = ""
    labels: list[str] = []
    reason: str = ""


def _review_error(exc: Exception) -> HTTPException:
    if isinstance(exc, review.BadInput):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=409, detail=str(exc))


@router.get("/api/review/labels")
def review_labels():
    return review.ERROR_LABELS


@router.get("/api/review/stats")
def review_stats(db: Session = Depends(get_db)):
    return review.stats(db)


# ---------- Mức tự chủ theo loại ca (R4) + lịch luật sư trực (R7) ----------
class AutonomyRequest(BaseModel):
    level: int = Field(ge=0, le=3)
    reason: str = ""


class DutyRequest(BaseModel):
    on_duty: bool
    lawyer: str | None = None
    backup: str | None = None


@router.get("/api/review/autonomy")
def review_autonomy(db: Session = Depends(get_db)):
    return autonomy.all_levels(db)


@router.patch("/api/review/autonomy/{ct}")
def review_autonomy_set(ct: str, req: AutonomyRequest, db: Session = Depends(get_db)):
    try:
        return autonomy.set_level(db, ct, req.level, req.reason)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/review/duty")
def review_duty(db: Session = Depends(get_db)):
    return sla.get_duty(db)


@router.patch("/api/review/duty")
def review_duty_set(req: DutyRequest, db: Session = Depends(get_db)):
    return sla.set_duty(db, req.on_duty, req.lawyer, req.backup)


@router.get("/api/review/cases/{case_id}/package")
def review_package(case_id: str, db: Session = Depends(get_db)):
    try:
        return review.package(db, case_id)
    except LookupError as exc:
        raise _review_error(exc) from exc


@router.post("/api/review/cases/{case_id}/act")
def review_act(case_id: str, req: ReviewActRequest, db: Session = Depends(get_db)):
    try:
        return review.act(db, case_id, req.action, req.text, req.labels, req.reason)
    except (review.BadInput, LookupError, ValueError) as exc:
        raise _review_error(exc) from exc


# ---------- Threads (tối giản) ----------
@router.get("/api/threads")
def list_threads(db: Session = Depends(get_db)):
    rows = db.scalars(select(Thread).order_by(Thread.updated_at.desc())).all()
    return [{"id": t.id, "title": t.title} for t in rows]


# ---------- Knowledge Graph ----------
@router.get("/api/graph")
def graph_route(
    query: str = "",
    top_k: int = 150,
    mode: Literal["law", "pv"] = "law",
    doc_id: str | None = None,
    uploads: bool = False,
    db: Session = Depends(get_db),
):
    """Knowledge graph quanh kết quả tra cứu. Cách dựng: app/graph/builder.py,
    chế độ ẩn pv: app/pv/graph.py. `doc_id`: xem đồ thị của một văn bản tải lên;
    `uploads`: cho phép văn bản đã duyệt lọt vào kết quả tra cứu."""
    if mode == "pv":
        return build_pv_graph(db, query, top_k)
    return build_graph(db, query, top_k, doc_id=doc_id, include_uploads=uploads)


# ---------- Câu hỏi phỏng vấn (/pv) ----------
@router.get("/api/pv")
def pv_library():
    """Thư viện câu hỏi phỏng vấn cho trang /pv. Nội dung: app/pv/data/*.md."""
    return {"layers": LAYERS, "groups": load_library()}


class PvChatMessage(BaseModel):
    role: str
    content: str


class PvChatRequest(BaseModel):
    message: str
    history: list[PvChatMessage] = []
    system_prompt: str | None = None
    group: str | None = None
    n: int = 5


@router.post("/api/pv/chat")
def pv_chat(req: PvChatRequest):
    """Chat phỏng vấn SSE. Lần đầu trả event 'system' kèm system_prompt để client lưu lại."""
    history = [{"role": m.role, "content": m.content} for m in req.history]

    def gen():
        try:
            for event, data in run_pv_chat(
                req.message, history,
                system_prompt=req.system_prompt,
                group=req.group,
                n=req.n,
            ):
                yield sse(event, data)
        except Exception as exc:  # noqa: BLE001
            yield sse("error", {"message": str(exc)})

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


# ---------- Human-in-loop: Escalation (câu hỏi không đủ căn cứ) ----------
# Vòng đầy đủ: người dùng gửi (pending) -> chuyên gia duyệt trên /dashboard hoặc
# /review, viết câu trả lời hoặc lý do từ chối (approved / denied) -> thẻ trong chat
# hỏi lại theo id và hiện kết quả. Từ R2, escalation nằm trong bảng `review_case`;
# tệp `data/escalations.json` cũ được nhập một lần ở lần dùng đầu tiên.
_ESC_FILE = Path("/app/data/escalations.json")
_esc_imported = False


def _import_escalations_once(db: Session) -> None:
    """Nhập escalations.json một lần cho mỗi tiến trình (idempotent theo id)."""
    global _esc_imported
    if _esc_imported:
        return
    _esc_imported = True
    try:
        n = review.import_json_escalations(db, _ESC_FILE)
        if n:
            logger.info("Đã nhập {} escalation cũ vào review_case", n)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Không nhập được escalations.json: {}", exc)


class EscalateRequest(BaseModel):
    question: str
    thread_id: str | None = None


class EscalateUpdate(BaseModel):
    status: Literal["approved", "denied"]
    reply: str = ""  # câu trả lời của chuyên gia, hoặc lý do từ chối


def _esc_case(db: Session, esc_id: str):
    """Thẻ phê duyệt cũ trong trình duyệt giữ id 32 ký tự; khi nhập vào review_case id bị cắt
    còn 16 ký tự (cột String(16)), nên tra cả hai dạng."""
    return db.get(ReviewCase, esc_id) or (db.get(ReviewCase, esc_id[:16]) if len(esc_id) > 16 else None)


@router.post("/api/escalate")
def escalate(req: EscalateRequest, db: Session = Depends(get_db)):
    """Ghi nhận câu hỏi không đủ căn cứ để nhà phát hành xem xét."""
    _import_escalations_once(db)
    case = ReviewCase(
        id=uuid.uuid4().hex[:16], question=mask(req.question).text, thread_id=req.thread_id,
        status="pending", source="user", risk_score="", reasons="[]",
    )
    db.add(case)
    db.commit()
    return {"id": case.id, "status": "pending"}


@router.get("/api/escalations")
def list_escalations(db: Session = Depends(get_db)):
    """Lấy danh sách câu hỏi chờ phê duyệt."""
    _import_escalations_once(db)
    rows = db.scalars(
        select(ReviewCase).where(ReviewCase.source == "user")
        .order_by(ReviewCase.created_at.desc())
    ).all()
    return [review.esc_row(c) for c in rows]


@router.get("/api/escalations/{esc_id}")
def get_escalation(esc_id: str, db: Session = Depends(get_db)):
    """Một yêu cầu: thẻ trong chat hỏi lại để biết chuyên gia đã xử lý chưa."""
    case = _esc_case(db, esc_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy escalation")
    return review.esc_row(case)


@router.patch("/api/escalations/{esc_id}")
def update_escalation(esc_id: str, req: EscalateUpdate, db: Session = Depends(get_db)):
    """Chuyên gia duyệt (kèm câu trả lời) hoặc từ chối (kèm lý do)."""
    reply = req.reply.strip()
    if req.status == "approved" and not reply:
        raise HTTPException(status_code=422, detail="Duyệt thì phải có câu trả lời của chuyên gia")
    case = _esc_case(db, esc_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy escalation")
    try:
        if req.status == "approved":
            draft = review.package(db, esc_id)["draft"]
            if draft is None:
                review.act(db, esc_id, "approve", text=reply)
            else:
                action = "light_edit" if reply != draft.strip() else "approve"
                review.act(db, esc_id, action, text=reply)
        else:
            review.act(db, esc_id, "reject", reason=reply or "Chuyên gia từ chối")
    except (review.BadInput, LookupError, ValueError) as exc:
        raise _review_error(exc) from exc
    return review.esc_row(case)


# ---------- Tải tài liệu lên (upload → OCR → KG) ----------
class UploadStatusRequest(BaseModel):
    status: Literal["approved", "rejected"]


def _upload_or_404(db: Session, upload_id: str):
    from app.db.models import UploadedFile

    row = db.get(UploadedFile, upload_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy tệp tải lên")
    return row


@router.post("/api/uploads")
def create_upload(
    background: BackgroundTasks,
    response: Response,
    file: UploadFile = File(...),
    title: str | None = Form(None),
    db: Session = Depends(get_db),
):
    """Tải tệp lên: ghi row `processing` rồi trích chữ/nạp node ở nền."""
    from app.upload import extract, service

    filename = file.filename or "tep"
    data = file.file.read(extract.MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Tệp rỗng")
    try:
        service.precheck(data, filename)
        row, is_new = service.register_upload(db, data, filename, title=title)
    except extract.TooLarge as exc:
        raise HTTPException(status_code=413, detail=f"Tệp quá lớn: {exc}") from exc
    except extract.UnsupportedFile as exc:
        raise HTTPException(status_code=415, detail=f"Định dạng không hỗ trợ: {exc}") from exc
    if not is_new:  # tệp trùng: trả ngay bản cũ
        return service.to_dict(row)
    background.add_task(service.process_upload, row.upload_id, data, filename, title)
    response.status_code = 202
    return service.to_dict(row)


@router.get("/api/uploads")
def list_uploads(db: Session = Depends(get_db)):
    from app.db.models import UploadedFile
    from app.upload import service

    rows = db.scalars(
        select(UploadedFile).order_by(UploadedFile.created_at.desc())
    ).all()
    return [service.to_dict(r) for r in rows]


@router.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str, db: Session = Depends(get_db)):
    from app.upload import service

    return service.to_dict(_upload_or_404(db, upload_id))


@router.get("/api/uploads/{upload_id}/text")
def get_upload_text(upload_id: str, db: Session = Depends(get_db)):
    """Toàn văn đã trích (trường preview trong danh sách chỉ là 2000 ký tự đầu)."""
    from app.upload import service

    text = service.full_text(db, _upload_or_404(db, upload_id))
    return {"upload_id": upload_id, "chars": len(text), "text": text}


@router.get("/api/uploads/{upload_id}/nodes")
def get_upload_nodes(upload_id: str, db: Session = Depends(get_db)):
    """Danh sách node của một tệp đã nạp (trang /upload xem nhanh cấu trúc)."""
    from app.db.models import NodeReference

    row = _upload_or_404(db, upload_id)
    nodes = []
    refs: dict[str, list[str]] = {}
    if row.doc_id:
        nodes = db.scalars(
            select(LegalNode)
            .where(LegalNode.doc_id == row.doc_id)
            .order_by(LegalNode.seq, LegalNode.node_id)
        ).all()
        if nodes:
            ids = [n.node_id for n in nodes]
            for from_id, to_id in db.execute(
                select(NodeReference.from_id, NodeReference.to_id).where(
                    NodeReference.from_id.in_(ids)
                )
            ).all():
                refs.setdefault(from_id, []).append(to_id)
    return {
        "upload_id": upload_id,
        "doc_id": row.doc_id,
        "nodes": [
            {
                "node_id": n.node_id,
                "level": n.level,
                "heading": n.heading or "",
                "preview": (n.text or "")[:200],
                "refs": refs.get(n.node_id, []),
            }
            for n in nodes
        ],
    }


@router.patch("/api/uploads/{upload_id}")
def review_upload(
    upload_id: str, req: UploadStatusRequest, db: Session = Depends(get_db)
):
    """Duyệt hoặc từ chối tệp; văn bản đã nạp đổi trạng thái theo."""
    from app.upload import service

    _upload_or_404(db, upload_id)
    return service.to_dict(service.set_status(db, upload_id, req.status))


@router.delete("/api/uploads/{upload_id}", status_code=204)
def delete_upload_route(upload_id: str, db: Session = Depends(get_db)):
    """Xoá tệp: node, dẫn chiếu, tệp trên đĩa và row."""
    from app.upload import service

    _upload_or_404(db, upload_id)
    service.remove_upload(db, upload_id)


# ---------- Data Gateway ----------
class GatewayPreviewRequest(BaseModel):
    text: str


@router.post("/api/gateway/preview")
def gateway_preview(req: GatewayPreviewRequest):
    """Xem trước phần văn bản thật sự rời hệ thống (không trả giá trị gốc)."""
    from app.gateway.classify import gate

    g = gate(req.text)
    return {"data_class": g.data_class, "masked": g.message, "counts": g.counts}
