"""API trang admin "Thu thập dữ liệu" (danh sách nguồn, chạy thử)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import deps as auth
from app.collect import registry
from app.db.base import get_db

router = APIRouter()
ADMIN = [Depends(auth.require("upload"))]


@router.get("/api/collect/sources", dependencies=ADMIN)
def collect_sources(db: Session = Depends(get_db)) -> dict:
    return {"sources": registry.status(db)}


@router.post("/api/collect/sources/{source_id}/probe", dependencies=ADMIN)
async def collect_probe(source_id: str) -> dict:
    """Chạy thử 5 mục (giãn cách 5 s, tôn trọng robots.txt); không ghi vào kho."""
    try:
        return await asyncio.to_thread(registry.probe, source_id)
    except KeyError as exc:
        raise HTTPException(404, "Không có nguồn này") from exc
