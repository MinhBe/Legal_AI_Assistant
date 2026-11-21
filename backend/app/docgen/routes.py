"""API GenAI soạn văn bản: đề xuất, chỉnh, chốt/khoá, soạn, gợi ý câu chữ."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import deps as auth
from app.db.base import get_db
from app.db.models import DocTemplate
from app.docgen import service as dg

router = APIRouter()


def _get(db: Session, tid: str) -> DocTemplate:
    t = db.get(DocTemplate, tid)
    if t is None:
        raise HTTPException(404, "Không có mẫu này")
    return t


@router.get("/api/docgen/templates", dependencies=[Depends(auth.require("chat"))])
def list_templates(db: Session = Depends(get_db), status: str | None = None) -> dict:
    q = select(DocTemplate).order_by(DocTemplate.updated_at.desc())
    if status:
        q = q.where(DocTemplate.status == status)
    return {"templates": [dg.to_dict(db, t) for t in db.execute(q).scalars().all()]}


@router.get("/api/docgen/templates/{tid}", dependencies=[Depends(auth.require("chat"))])
def get_template(tid: str, db: Session = Depends(get_db)) -> dict:
    return dg.to_dict(db, _get(db, tid), detail=True)


@router.post("/api/docgen/templates", status_code=201)
def propose(body: dict = Body(...), db: Session = Depends(get_db),
            user: dict = Depends(auth.require("escalate"))) -> dict:
    """Luật sư / người dùng có quyền đề xuất mẫu; admin chỉnh và chốt sau."""
    try:
        t = dg.propose(db, name=str(body.get("name") or ""), kind=str(body.get("kind") or "khac"),
                       body=str(body.get("body") or ""), basis=list(body.get("legal_basis") or []),
                       note=body.get("note"), author=user.get("username") or "anonymous")
    except dg.DocgenError as exc:
        raise HTTPException(400, str(exc)) from exc
    return dg.to_dict(db, t, detail=True)


@router.post("/api/docgen/lint", dependencies=[Depends(auth.require("chat"))])
def lint(body: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    text = str(body.get("body") or "")
    fields = dg.default_fields(text, body.get("fields"))
    return {"fields": fields, "issues": dg.lint(db, text, fields, list(body.get("legal_basis") or []))}


@router.put("/api/docgen/templates/{tid}")
def save(tid: str, body: dict = Body(...), db: Session = Depends(get_db),
         user: dict = Depends(auth.require("upload"))) -> dict:
    t = _get(db, tid)
    try:
        dg.save_version(db, t, body=str(body.get("body") or ""), fields=body.get("fields"),
                        basis=list(body.get("legal_basis") or []), note=body.get("note"),
                        author=user.get("username") or "admin")
    except dg.DocgenError as exc:
        raise HTTPException(400, str(exc)) from exc
    return dg.to_dict(db, t, detail=True)


@router.post("/api/docgen/templates/{tid}/lock")
def lock(tid: str, db: Session = Depends(get_db), user: dict = Depends(auth.require("upload"))) -> dict:
    t = _get(db, tid)
    v, issues = dg.lock(db, t, by=user.get("username") or "admin")
    if v is None:
        raise HTTPException(422, {"message": "Chưa khoá được: còn lỗi", "issues": issues})
    return {"template": dg.to_dict(db, t, detail=True), "issues": issues}


@router.post("/api/docgen/templates/{tid}/generate", dependencies=[Depends(auth.require("chat"))])
def generate(tid: str, body: dict = Body(...), db: Session = Depends(get_db)) -> dict:
    try:
        return dg.generate(db, _get(db, tid), dict(body.get("values") or {}), body.get("version"))
    except dg.DocgenError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/docgen/suggest", dependencies=[Depends(auth.require("escalate"))])
async def suggest(body: dict = Body(...)) -> dict:
    from app.llm.router import get_router

    try:
        text = await asyncio.to_thread(dg.suggest, get_router(), str(body.get("label") or ""),
                                       str(body.get("context") or ""))
    except Exception as exc:  # noqa: BLE001 — nhà cung cấp lỗi: báo rõ, không treo
        raise HTTPException(503, f"Chưa gợi ý được: {str(exc)[:120]}") from exc
    return {"text": text, "note": "Gợi ý của mô hình, luật sư xem và sửa trước khi dùng"}
