"""Báo động cho luật sư khi một tin mới ảnh hưởng lớn (LI2b).

Tin ảnh hưởng `cao` (hoặc thuộc watchlist ưu tiên 3) sinh đúng một ca duyệt `review_case`
nguồn `intel`; ca đã tạo thì ghi id vào dòng `intel_impact` nên phân tích lại không sinh ca
thứ hai. Webhook là tuỳ chọn: chưa đặt `intel_webhook_url` thì không gọi mạng.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import IntelItem, ReviewCase
from app.intel import store


def _reasons(analysis: dict[str, Any], impact: dict[str, Any]) -> list[dict[str, str]]:
    out = [{"code": "intel", "message": str(analysis.get("impact_reason") or "")}]
    summary = str(impact.get("summary") or "")
    if summary:
        out.append({"code": "intel", "message": summary})
    return out


def _webhook(item: IntelItem, analysis: dict[str, Any], impact: dict[str, Any]) -> None:
    """Báo tin sang hệ thống khác nếu có đặt; hỏng thì bỏ qua, không chặn phân tích."""
    url = getattr(get_settings(), "intel_webhook_url", "") or ""
    if not url:
        return
    try:
        httpx.post(
            url,
            json={
                "id": item.id,
                "title": item.title,
                "url": item.url,
                "impact": analysis.get("impact"),
                "summary": impact.get("summary"),
            },
            timeout=5.0,
        )
    except Exception as exc:  # noqa: BLE001 — mạng hỏng không được làm hỏng phân tích
        logger.warning("Không gửi được webhook tin {}: {}", item.id, exc)


def raise_for(
    db: Session, item: IntelItem, analysis: dict[str, Any], impact: dict[str, Any]
) -> str | None:
    """Tạo (một lần) ca duyệt cho tin ảnh hưởng cao; trả id ca nếu tin đã có ca."""
    row = store.get_impact(db, item.id) or store.save_impact(db, item.id, impact)
    if analysis.get("impact") != "cao" and int(analysis.get("priority") or 0) < 3:
        return row.case_id
    if row.case_id:
        return row.case_id
    case = ReviewCase(
        id=uuid.uuid4().hex[:16],
        question=item.title,
        risk_score="intel",
        reasons=json.dumps(_reasons(analysis, impact), ensure_ascii=False),
        status="pending",
        source="intel",
        case_type="intel",
    )
    db.add(case)
    row.case_id = case.id
    db.commit()
    _webhook(item, analysis, impact)
    return case.id
