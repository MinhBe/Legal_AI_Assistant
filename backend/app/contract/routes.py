"""API rà soát hợp đồng lao động (luật code, không gọi LLM, không lưu nội dung)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import deps as auth
from app.contract import review
from app.db.base import get_db

router = APIRouter()
CHAT = [Depends(auth.require("chat"))]
MAX_CHARS = 60_000
MAX_BYTES = 10 * 1024 * 1024


class ReviewIn(BaseModel):
    text: str = Field(min_length=20, max_length=MAX_CHARS)
    as_of: date | None = None


@router.post("/api/contract/review", dependencies=CHAT)
def contract_review(body: ReviewIn, db: Session = Depends(get_db)) -> dict:
    return review.check(body.text, as_of=body.as_of, db=db)


@router.post("/api/contract/review-file", dependencies=CHAT)
async def contract_review_file(
    file: UploadFile = File(...),
    as_of: date | None = Form(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Nhận DOCX/PDF/ảnh/TXT, rút chữ rồi rà soát. Tệp không được lưu lại."""
    from app.upload.extract import extract

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "Tệp quá 10 MB")
    try:
        ex = extract(data, file.filename or "hop-dong.txt")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    text = ex.text
    if len(text.strip()) < 20:
        raise HTTPException(422, "Không đọc được chữ trong tệp")
    out = review.check(text[:MAX_CHARS], as_of=as_of, db=db)
    out["source"] = {"filename": file.filename, "chars": len(text)}
    return out
