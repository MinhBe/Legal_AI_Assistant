"""Verifier bằng code cho câu trả lời có trích dẫn (T5, design §4, §5.3).

Ba kiểm tra, theo thứ tự: trích dẫn có thật (trong kết quả truy hồi và trong kho),
còn hiệu lực tại ngày sự kiện, và mọi đoạn trích trong «…»/"…" phải khớp nguyên văn
với điều được trích. Không gọi LLM; ngày do code quyết định.

    verify(db, result, hits, as_of) -> {"ok", "checked", "problems", "dropped"}
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from loguru import logger

MIN_QUOTE = 12  # đoạn ngắn hơn thường là tên điều khoản, không phải trích dẫn

# «…», “…” và "…" — nhóm nào khớp thì lấy nhóm đó
_QUOTE_RE = re.compile(r"«([^«»]+)»|“([^“”]+)”|\"([^\"]+)\"")

# Gộp khoảng trắng, quy kiểu nháy/gạch về ASCII; giữ nguyên chữ hoa và dấu tiếng Việt.
_NORM = str.maketrans({
    "“": '"', "”": '"', "„": '"', "«": '"', "»": '"',
    "‘": "'", "’": "'", "`": "'", "´": "'",
    "–": "-", "—": "-", "−": "-",
})

_NODE_SQL = text(
    """
    SELECT n.node_id, n.doc_id, n.article_no, n.heading,
           n.effective_from, n.effective_to, n.text, d.title
    FROM legal_node n JOIN legal_document d ON d.doc_id = n.doc_id
    WHERE n.node_id = :id
    """
)
_VERSION_SQL = text(
    """
    SELECT valid_from, valid_to FROM provision_version
    WHERE provision_key = :id ORDER BY valid_from
    """
)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.translate(_NORM)).strip()


def _node_row(db: Session, node_id: str) -> dict | None:
    row = db.execute(_NODE_SQL, {"id": node_id}).first()
    return dict(row._mapping) if row else None


def _version_rows(db: Session, node_id: str) -> list[dict]:
    return [dict(r._mapping) for r in db.execute(_VERSION_SQL, {"id": node_id})]


def _quotes(text_: str) -> list[str]:
    out = []
    for m in _QUOTE_RE.finditer(text_ or ""):
        span = next(g for g in m.groups() if g is not None).strip()
        if len(span) >= MIN_QUOTE:
            out.append(span)
    return out


def _cited_ids(result: dict) -> list[str]:
    ids = [str(i) for i in (result.get("citation_node_ids") or [])]
    for s in result.get("sections") or []:
        ids += [str(i) for i in (s.get("citation_node_ids") or [])]
    seen: list[str] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


def _in_force(db: Session, node_id: str, node: dict, as_of: date) -> str | None:
    """None nếu còn hiệu lực; ngược lại là lý do tiếng Việt."""
    versions = _version_rows(db, node_id)
    if versions:
        for v in versions:
            vf, vt = v.get("valid_from"), v.get("valid_to")
            if (vf is None or vf <= as_of) and (vt is None or vt > as_of):
                return None
        if all(v.get("valid_from") is not None and v["valid_from"] > as_of for v in versions):
            return "chưa có hiệu lực"
        return "không còn hiệu lực"
    # chưa backfill provision_version: dùng ngày hiệu lực gắn trên node
    vf, vt = node.get("effective_from"), node.get("effective_to")
    if vf and vf > as_of:
        return "chưa có hiệu lực"
    if vt and vt <= as_of:
        return "không còn hiệu lực"
    return None


def _label(node: dict, hit: dict | None) -> str:
    if hit and hit.get("display"):
        return str(hit["display"])
    if node.get("article_no"):
        return f"Điều {node['article_no']} ({node.get('title') or node.get('doc_id')})"
    return str(node.get("node_id"))


def verify(db: Session, result: dict, hits: list[dict], as_of: date) -> dict:
    """Kiểm trích dẫn của một câu trả lời đã parse; danh sách `dropped` là căn cứ phải bỏ."""
    hits_by_id = {h["node_id"]: h for h in hits}
    cited = _cited_ids(result)
    problems: list[dict] = []
    dropped: list[str] = []
    grounded: dict[str, str] = {}  # node_id -> text đã chuẩn hoá, chỉ node qua được 2 kiểm tra đầu

    for nid in cited:
        hit = hits_by_id.get(nid)
        if hit is None:
            problems.append({
                "check": "exists", "node_id": nid,
                "message": f"Căn cứ {nid} không có trong kết quả truy hồi",
            })
            dropped.append(nid)
            continue
        node = _node_row(db, nid)
        if node is None:
            # hits sinh ra từ legal_node; lệch kho là sự cố dữ liệu, không phải LLM bịa
            logger.warning("Verifier: {} có trong hits nhưng không có trong legal_node", nid)
            grounded[nid] = _norm(str(hit.get("text") or ""))
            continue
        reason = _in_force(db, nid, node, as_of)
        if reason:
            problems.append({
                "check": "in_force", "node_id": nid,
                "message": f"{_label(node, hit)} {reason} tại ngày {as_of.strftime('%d/%m/%Y')}",
            })
            dropped.append(nid)
            continue
        grounded[nid] = _norm(str(hit.get("text") or node.get("text") or ""))

    def check_quotes(body: str, ids: list[str]) -> None:
        texts = [grounded[i] for i in ids if i in grounded]
        for quote in _quotes(body):
            q = _norm(quote)
            if not any(q in t for t in texts):
                problems.append({
                    "check": "quotes", "quote": quote,
                    "message": f"Trích dẫn không khớp nguyên văn: «{quote}»",
                })

    global_ids = [str(i) for i in (result.get("citation_node_ids") or [])]
    check_quotes(result.get("summary") or result.get("answer") or "", global_ids)
    for s in result.get("sections") or []:
        check_quotes(str(s.get("detail") or ""), [str(i) for i in (s.get("citation_node_ids") or [])])

    return {"ok": not problems, "checked": len(cited), "problems": problems, "dropped": dropped}
