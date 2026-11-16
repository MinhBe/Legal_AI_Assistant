"""Hồ sơ câu trả lời pháp lý (T7, design §5.3).

Mỗi câu trả lời có căn cứ được lưu một bản ghi: câu hỏi/câu trả lời đã che PII, các
điều được trích kèm phiên bản đúng tại `as_of`, khung thời gian (T2), verifier (T5),
ảnh chụp kho và model đã thắng. Ghi hỏng không bao giờ được làm hỏng chat.

    rec = build(ctx, events, thread_id)   # None nếu không phải câu trả lời pháp lý
    save(db, rec) -> id
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.db.base import SessionLocal
from app.db.models import AnswerRecord, LegalDocument, ProvisionVersion
from app.obs import metrics

_JSON_FIELDS = ("provisions", "timeframe", "verifier", "corpus_snapshot")
_DATE_FIELDS = ("advice_date", "event_date", "as_of")

_PROVISION_SQL = text(
    """
    SELECT id, doc_id, valid_from, valid_to, text_hash
    FROM provision_version
    WHERE provision_key = :key
      AND (valid_from IS NULL OR valid_from <= :as_of)
      AND (valid_to IS NULL OR valid_to > :as_of)
    ORDER BY valid_from DESC NULLS LAST
    LIMIT 1
    """
)
_NODE_SQL = text(
    """
    SELECT doc_id, effective_from, effective_to, text_hash
    FROM legal_node WHERE node_id = :key
    """
)


def _day(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _cited(events: list[tuple[str, object]]) -> list[str]:
    ids: list[str] = []
    for event, data in events:
        if not isinstance(data, dict):
            continue
        if event == "citation":
            cand = [data.get("node_id")]
        elif event == "section":
            cand = [c.get("node_id") for c in data.get("citations") or [] if isinstance(c, dict)]
        else:
            continue
        for node_id in cand:
            if node_id and node_id not in ids:
                ids.append(node_id)
    return ids


def _provisions(db: Session, nodes: list[str], as_of: date) -> list[dict]:
    out: list[dict] = []
    for node_id in nodes:
        row = db.execute(_PROVISION_SQL, {"key": node_id, "as_of": as_of}).first()
        if row is not None:
            out.append({
                "node_id": node_id, "doc_id": row.doc_id,
                "valid_from": row.valid_from, "valid_to": row.valid_to,
                "text_hash": row.text_hash, "version_id": row.id,
            })
            continue
        node = db.execute(_NODE_SQL, {"key": node_id}).first()
        out.append({
            "node_id": node_id,
            "doc_id": node.doc_id if node else None,
            "valid_from": node.effective_from if node else None,
            "valid_to": node.effective_to if node else None,
            "text_hash": node.text_hash if node else None,
            "version_id": None,
        })
    return out


def _snapshot(db: Session) -> dict:
    last = db.scalar(
        select(func.max(LegalDocument.created_at)).where(
            LegalDocument.doc_type.is_distinct_from("upload")
        )
    )
    return {
        "last_ingest": _day(last).isoformat() if last else None,
        "n_documents": db.scalar(select(func.count()).select_from(LegalDocument)) or 0,
        "n_provisions": db.scalar(select(func.count()).select_from(ProvisionVersion)) or 0,
    }


def _facts(nodes: list[str], as_of: date) -> tuple[list[dict], dict]:
    """Căn cứ + ảnh chụp kho; DB hỏng thì vẫn giữ danh sách node đã trích."""
    empty = {"last_ingest": None, "n_documents": 0, "n_provisions": 0}
    try:
        db = SessionLocal()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Không mở được DB để ghi hồ sơ: {}", exc)
        return [_provision_stub(n) for n in nodes], empty
    try:
        return _provisions(db, nodes, as_of), _snapshot(db)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Không tra được căn cứ cho hồ sơ: {}", exc)
        return [_provision_stub(n) for n in nodes], empty
    finally:
        db.close()


def _provision_stub(node_id: str) -> dict:
    return {
        "node_id": node_id, "doc_id": None, "valid_from": None,
        "valid_to": None, "text_hash": None, "version_id": None,
    }


def _winner(ctx: dict) -> tuple[str | None, str | None]:
    calls = [c for c in ctx.get("llm") or [] if isinstance(c, dict)]
    ok = [c for c in calls if not c.get("error")]
    win = next((c for c in ok if c.get("won")), ok[-1] if ok else None)
    return (win.get("provider"), win.get("model")) if win else (None, None)


def build(
    ctx: dict, events: list[tuple[str, object]], thread_id: str | None
) -> dict | None:
    """Hồ sơ từ các sự kiện đã phát; None khi không có `timeframe` (không phải câu trả lời luật)."""
    tf: dict | None = None
    verifier: dict | None = None
    category = None
    chunks: list[str] = []
    for event, data in events:
        if not isinstance(data, dict):
            continue
        if event == "token":
            chunks.append(data.get("text") or "")
        elif event == "timeframe":
            tf = data
        elif event == "verifier":
            verifier = data
        elif event == "done":
            category = data.get("category") or category
    if tf is None:
        return None

    # Câu hỏi trong ctx đã được pipeline che; câu trả lời phải che lại (client nhận bản gốc).
    answer = "".join(chunks)
    scrubbed = {"answer": answer}
    metrics._scrub_pii(scrubbed, ctx.get("_pii_mapping") or {})
    answer = scrubbed["answer"]

    advice = _day(tf.get("advice_date"))
    as_of = _day(tf.get("as_of")) or advice or date.today()
    nodes = _cited(events)
    provisions, snapshot = _facts(nodes, as_of)
    provider, model = _winner(ctx)

    return {
        "id": uuid.uuid4().hex[:12],
        "thread_id": thread_id,
        "request_id": ctx.get("request_id"),
        "data_class": ctx.get("data_class") or "C",
        "question": ctx.get("question") or "",
        "answer": answer,
        "advice_date": advice or as_of,
        "event_date": _day(tf.get("event_date")),
        "as_of": as_of,
        "provisions": provisions,
        "timeframe": tf,
        "verifier": verifier,
        "corpus_snapshot": snapshot,
        "prompt_version": (ctx.get("prompt_version") or "")[:32],
        "provider": provider,
        "model": model,
        "category": category,
    }


def _column(rec: dict, name: str) -> Any:
    value = rec.get(name)
    if name in _JSON_FIELDS:
        return None if value is None else json.dumps(value, ensure_ascii=False, default=str)
    if name in _DATE_FIELDS:
        return _day(value)
    return value


def save(db: Session, rec: dict) -> str:
    """Ghi một hồ sơ, trả về id."""
    names = [c.name for c in AnswerRecord.__table__.columns if c.name not in ("id", "created_at")]
    rec_id = rec.get("id") or uuid.uuid4().hex[:12]
    db.add(AnswerRecord(id=rec_id, **{n: _column(rec, n) for n in names}))
    db.commit()
    return rec_id


def _row(obj: AnswerRecord, *, with_answer: bool = True) -> dict:
    out: dict[str, Any] = {}
    for col in obj.__table__.columns:
        value = getattr(obj, col.name)
        if isinstance(value, date):  # datetime cũng là date
            value = value.isoformat()
        elif col.name in _JSON_FIELDS and isinstance(value, str):
            try:
                value = json.loads(value)
            except ValueError:
                pass
        if col.name == "answer" and not with_answer:
            continue
        out[col.name] = value
    return out


def get(db: Session, rec_id: str) -> dict | None:
    obj = db.get(AnswerRecord, rec_id)
    return _row(obj) if obj else None


def list_recent(db: Session, limit: int = 50) -> list[dict]:
    rows = db.scalars(
        select(AnswerRecord).order_by(AnswerRecord.created_at.desc()).limit(limit)
    ).all()
    return [_row(r, with_answer=False) for r in rows]
