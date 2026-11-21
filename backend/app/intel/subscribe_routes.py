"""API đăng ký theo dõi văn bản mới theo lĩnh vực."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import deps as auth
from app.db.base import get_db
from app.intel import subscribe
from app.rag import domain

router = APIRouter()
USER = Depends(auth.require("chat"))


class SubIn(BaseModel):
    name: str = Field(default="", max_length=120)
    domains: list[str] = Field(default_factory=list, max_length=len(domain.LABELS))
    keywords: list[str] = Field(default_factory=list, max_length=subscribe.MAX_KEYWORDS)


def _own(db: Session, user: dict, sub_id: int):
    sub = subscribe.get(db, subscribe.owner_of(user), sub_id)
    if sub is None:
        raise HTTPException(404, "Không có đăng ký này")
    return sub


@router.get("/api/intel/domains")
def domains() -> dict:
    return {"domains": [{"id": k, "label": v} for k, v in domain.LABELS.items()]}


@router.get("/api/intel/subscriptions")
def list_subs(user: dict = USER, db: Session = Depends(get_db)) -> dict:
    subs = subscribe.list_for(db, subscribe.owner_of(user))
    return {"subscriptions": [subscribe.feed(db, s, limit=0)["subscription"] for s in subs]}


@router.post("/api/intel/subscriptions")
def create_sub(body: SubIn, user: dict = USER, db: Session = Depends(get_db)) -> dict:
    try:
        sub = subscribe.create(db, subscribe.owner_of(user), body.name, body.domains, body.keywords)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return subscribe.to_dict(sub)


@router.get("/api/intel/subscriptions/{sub_id}/feed")
def sub_feed(sub_id: int, limit: int = 50, user: dict = USER, db: Session = Depends(get_db)) -> dict:
    return subscribe.feed(db, _own(db, user, sub_id), limit=max(1, min(limit, 200)))


@router.post("/api/intel/subscriptions/{sub_id}/read")
def sub_read(sub_id: int, user: dict = USER, db: Session = Depends(get_db)) -> dict:
    return subscribe.to_dict(subscribe.mark_read(db, _own(db, user, sub_id)), 0)


@router.delete("/api/intel/subscriptions/{sub_id}")
def sub_delete(sub_id: int, user: dict = USER, db: Session = Depends(get_db)) -> dict:
    subscribe.delete(db, _own(db, user, sub_id))
    return {"deleted": sub_id}
