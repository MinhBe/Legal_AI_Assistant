"""Ảnh hưởng của một tin mới ra ngoài văn bản (LI2b).

Sau khi Dahl đã phân tích một tin, CODE tính xem tin đó chạm vào đâu: điều khoản nào trong
kho, máy tính nào có thể sai đi, ca golden nào và hồ sơ tra cứu nào đã trích điều đó. Không
gọi thêm LLM — chỉ đọc `analysis` đã lưu và dữ liệu sẵn có.

Từ khoá so khớp trên chữ đã bỏ dấu (`guard.normalize`), nên "mức lương" khớp cả "muc luong".
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.agent.guard import normalize
from app.db.models import AnswerRecord, IntelImpact, IntelItem, LegalDocument, LegalNode
from app.eval.gate import article_of
from app.eval.golden import load_golden
from app.intel import store

MAX_ARTICLES = 30
MAX_GOLDEN = 20
MAX_ANSWERS = 20
ANSWER_SCAN = 500  # số hồ sơ gần nhất đem so
QUESTION_CHARS = 120

#: (từ khoá hiển thị, các máy tính có thể sai đi) — thứ tự quyết định thứ tự ưu tiên
CALC_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("mức lương", ("severance", "job-loss", "unlawful-dismissal")),
    ("lương tối thiểu", ("severance", "job-loss", "unlawful-dismissal")),
    ("tiền lương", ("severance", "job-loss", "unlawful-dismissal")),
    ("báo trước", ("notice",)),
    ("chấm dứt hợp đồng", ("notice",)),
    ("trợ cấp thôi việc", ("severance", "job-loss", "service-years")),
    ("mất việc", ("severance", "job-loss", "service-years")),
    ("thời gian làm việc", ("severance", "job-loss", "service-years")),
    ("thời hiệu", ("limitation",)),
    ("tranh chấp lao động", ("limitation",)),
)
_NORMALIZED = tuple((keyword, normalize(keyword), kinds) for keyword, kinds in CALC_KEYWORDS)


def keywords(text: str) -> list[tuple[str, tuple[str, ...]]]:
    """Các từ khoá (giữ dấu) xuất hiện trong `text` đã bỏ dấu."""
    haystack = normalize(text or "")
    return [(k, kinds) for k, bare, kinds in _NORMALIZED if bare in haystack]


def _calculators(text: str) -> list[dict[str, str]]:
    out: dict[str, str] = {}
    for keyword, kinds in keywords(text):
        for kind in kinds:
            out.setdefault(kind, keyword)
    return [{"kind": kind, "reason": f"nhắc “{kw}”"} for kind, kw in out.items()]


def _label(node: LegalNode) -> str:
    parts = []
    if node.article_no:
        parts.append(f"Điều {node.article_no}")
    if node.clause_no:
        parts.append(f"Khoản {node.clause_no}")
    if node.point_letter:
        parts.append(f"Điểm {node.point_letter}")
    head = " ".join(parts) or node.node_id
    if node.level == "article" and node.heading:
        return f"{head} — {node.heading}"
    return head


def _nodes(db: Session, analysis: dict[str, Any]) -> list[LegalNode]:
    """Node bị ảnh hưởng + các Điều của văn bản mà tin nói là sửa đổi/thay thế."""
    found: dict[str, LegalNode] = {}
    affected = [str(n).strip() for n in analysis.get("affected_nodes") or [] if n]
    if affected:
        for node in db.scalars(select(LegalNode).where(LegalNode.node_id.in_(affected))):
            found[node.node_id] = node
    numbers = [
        str(n).strip().lower()
        for n in (analysis.get("amends") or []) + (analysis.get("replaces") or [])
        if str(n).strip()
    ]
    if numbers:
        docs = select(LegalDocument.doc_id).where(func.lower(LegalDocument.number).in_(numbers))
        rows = db.scalars(
            select(LegalNode)
            .where(LegalNode.doc_id.in_(docs), LegalNode.level == "article")
            .order_by(LegalNode.doc_id, LegalNode.article_no)
        )
        for node in rows:
            found.setdefault(node.node_id, node)
    return list(found.values())[:MAX_ARTICLES]


def _golden(hits: bool, articles: set[str]) -> list[dict[str, str]]:
    """Ca golden chạm vào một Điều bị ảnh hưởng, hoặc hỏi đúng chủ đề của máy tính."""
    try:
        rows = load_golden()
    except OSError as exc:  # thiếu tệp thì coi như không có ca nào
        logger.warning("Không đọc được golden set: {}", exc)
        return []
    out: list[dict[str, str]] = []
    for row in rows:
        cited = {article_of(str(p.get("node_id") or "")) for p in row.get("expected_provisions") or []}
        if not ((cited & articles) or (hits and keywords(row.get("question") or ""))):
            continue
        out.append({"id": row.get("id") or "", "question": row.get("question") or ""})
        if len(out) >= MAX_GOLDEN:
            break
    return out


def _answers(db: Session, hits: bool, articles: set[str]) -> list[dict[str, Any]]:
    """Hồ sơ câu trả lời đã trích điều bị ảnh hưởng, hoặc hỏi đúng chủ đề; mới nhất trước."""
    out: list[dict[str, Any]] = []
    rows = db.scalars(
        select(AnswerRecord).order_by(AnswerRecord.created_at.desc()).limit(ANSWER_SCAN)
    )
    for rec in rows:
        try:
            cited = {str(p.get("node_id") or "") for p in json.loads(rec.provisions or "[]")}
        except (ValueError, TypeError):
            cited = set()
        hit = any(n in articles or article_of(n) in articles for n in cited if n)
        if not (hit or (hits and keywords(rec.question or ""))):
            continue
        out.append({
            "id": rec.id,
            "created_at": rec.created_at.isoformat() if rec.created_at else None,
            "question": (rec.question or "")[:QUESTION_CHARS],
        })
        if len(out) >= MAX_ANSWERS:
            break
    return out


def compute(db: Session, item: IntelItem, analysis: dict[str, Any]) -> dict[str, Any]:
    """Tính và lưu ảnh hưởng của một tin; trả về đúng dict đã lưu."""
    text = " ".join([
        item.title or "",
        str(analysis.get("topic") or ""),
        str(analysis.get("what_changes") or ""),
    ])
    nodes = _nodes(db, analysis)
    articles = {node.node_id for node in nodes} | {article_of(node.node_id) for node in nodes}
    calcs = _calculators(text)
    data: dict[str, Any] = {
        "articles": [{"node_id": n.node_id, "display": _label(n)} for n in nodes],
        "calculators": calcs,
        "golden": _golden(bool(calcs), articles),
        "answers": _answers(db, bool(calcs), articles),
    }
    data["summary"] = (
        f"Ảnh hưởng: {len(data['articles'])} điều luật, {len(data['calculators'])} máy tính, "
        f"{len(data['golden'])} câu golden, {len(data['answers'])} hồ sơ tra cứu"
    )
    store.save_impact(db, item.id, data)
    return data


def active_calc_warnings(db: Session) -> dict[str, list[dict[str, str]]]:
    """Máy tính nào đang có tin chờ luật sư duyệt có thể làm kết quả sai đi."""
    out: dict[str, list[dict[str, str]]] = {}
    try:
        rows = db.execute(
            select(IntelImpact, IntelItem)
            .join(IntelItem, IntelItem.id == IntelImpact.item_id)
            .where(IntelItem.status == "analysed")
        ).all()
    except SQLAlchemyError as exc:  # bảng chưa có (DB cũ) thì bỏ qua cảnh báo
        logger.warning("Không đọc được intel_impact: {}", exc)
        return out
    for impact, item in rows:
        try:
            level = (json.loads(item.analysis or "{}")).get("impact")
        except ValueError:
            level = None
        if level not in ("cao", "trung bình"):
            continue
        for calc in store.impact_dict(impact)["calculators"]:
            out.setdefault(calc["kind"], []).append(
                {"item_id": item.id, "title": item.title, "url": item.url}
            )
    return out
