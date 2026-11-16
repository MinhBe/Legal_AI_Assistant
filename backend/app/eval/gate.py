"""Cổng đánh giá G4 (design §11.2–11.4, §15.7): đo chất lượng cục bộ, không gọi LLM.

Mỗi chỉ số là một dict: value, n (số ca), n_reviewed (số ca đã duyệt), errors
(số ca sai; None với chỉ số liên tục như mrr), bound (cận trên 3/n khi errors = 0).
"""

from __future__ import annotations

import subprocess
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.agent.guard import looks_like_injection
from app.eval.golden import load_golden
from app.gateway.pii import mask
from app.rag.search import search_nodes

BASELINE = Path(__file__).resolve().parents[2] / "eval" / "gate_baseline.json"
TOLERANCE = 0.02  # điểm phần trăm cho phép tụt so với baseline (§15.7)

# 20 câu giả lập, đủ 7 loại thực thể G1. Giá trị là phần phải biến mất sau khi che.
PII_CASES: list[tuple[str, tuple[str, ...]]] = [
    ("Email của tôi là nva.kd@example.com, nhờ tư vấn.", ("nva.kd@example.com",)),
    ("Tôi là Trần Văn Bình, số điện thoại 0987 654 321.", ("Trần Văn Bình", "0987 654 321")),
    ("CCCD 001203004567 của tôi bị mất, có phải làm lại không?", ("001203004567",)),
    ("Lương tháng của tôi là 15.000.000 đồng.", ("15.000.000 đồng",)),
    ("STK 1903 4567 8901 23 tại Techcombank bị đóng băng.", ("1903 4567 8901 23",)),
    ("Tôi thường trú tại số 45 phố Huế, phường Hàng Bài, Hà Nội.", ("số 45 phố Huế, phường Hàng Bài, Hà Nội",)),
    ("Chị Lê Thị Hoa gọi lại cho tôi sau 17 giờ.", ("Lê Thị Hoa",)),
    ("Ông Nguyễn Văn An cần xác nhận hợp đồng lao động.", ("Nguyễn Văn An",)),
    ("Họ tên: Phạm Minh Châu, chức danh kế toán.", ("Phạm Minh Châu",)),
    ("Tôi là Đỗ Thị Mai, email mai.dt@example.org.", ("Đỗ Thị Mai", "mai.dt@example.org")),
    ("Số tài khoản: 0071001234567 mở tại Vietcombank.", ("0071001234567",)),
    ("Tài khoản số 0123 4567 89 nhận trợ cấp thôi việc.", ("0123 4567 89",)),
    ("Tiền lương làm thêm giờ tuần trước là 2.500.000 đồng.", ("2.500.000 đồng",)),
    ("Tôi được trả 12 triệu đồng mỗi tháng.", ("12 triệu đồng",)),
    ("Số điện thoại liên hệ 0912 345 678, gọi giờ hành chính.", ("0912 345 678",)),
    ("Anh Hoàng Văn Đức xin nghỉ phép năm.", ("Hoàng Văn Đức",)),
    ("Địa chỉ công ty: số 8 Tràng Thi, quận Hoàn Kiếm.", ("số 8 Tràng Thi, quận Hoàn Kiếm",)),
    ("Tôi cư trú tại số 12 ngõ 34 phố Mẫu, phường An Bình.", ("số 12 ngõ 34 phố Mẫu, phường An Bình",)),
    ("Vui lòng gửi tới bich.nt@example.vn trước thứ sáu.", ("bich.nt@example.vn",)),
    ("Bà Vũ Thị Lan, CMND 123456789, đã nghỉ việc.", ("Vũ Thị Lan", "123456789")),
]

UPLOAD_QUERIES = [
    "thời gian thử việc tối đa",
    "nghỉ phép năm bao nhiêu ngày",
    "trợ cấp thôi việc khi nghỉ việc",
    "làm thêm giờ tính lương thế nào",
    "kỷ luật lao động sa thải",
]


def article_of(node_id: str) -> str:
    """tiền tố Điều của node: blld2019-d113-k1 -> blld2019-d113."""
    return "-".join(node_id.split("-")[:2])


def _squash(s: str) -> str:
    return "".join(s.split()).lower()


def _rate(ok: int, n: int, n_reviewed: int = 0) -> dict[str, Any]:
    errors = n - ok
    return {
        "value": round(ok / n, 4) if n else None,
        "n": n,
        "n_reviewed": n_reviewed,
        "errors": errors,
        "bound": round(3 / n, 4) if n and errors == 0 else None,
    }


def _as_of(row: dict) -> date | None:
    return date.fromisoformat(row["event_date"]) if row.get("event_date") else None


def _provision_articles(row: dict) -> set[str]:
    return {article_of(p["node_id"]) for p in row.get("expected_provisions") or []}


def _retrieval_metric(db: Session, rows: list[dict], k: int) -> dict[str, Any]:
    ok = 0
    for r in rows:
        hits = search_nodes(db, r["question"], top_k=k, as_of=_as_of(r))
        if _provision_articles(r) & {article_of(h["node_id"]) for h in hits}:
            ok += 1
    return _rate(ok, len(rows), sum(1 for r in rows if r.get("reviewed")))


def _mrr(db: Session, rows: list[dict]) -> dict[str, Any]:
    total = 0.0
    for r in rows:
        want = _provision_articles(r)
        hits = search_nodes(db, r["question"], top_k=8, as_of=_as_of(r))
        rank = next((i for i, h in enumerate(hits, 1) if article_of(h["node_id"]) in want), None)
        total += 1 / rank if rank else 0.0
    return {
        "value": round(total / len(rows), 4) if rows else None,
        "n": len(rows),
        "n_reviewed": sum(1 for r in rows if r.get("reviewed")),
        "errors": None,
        "bound": None,
    }


def _version_correct(db: Session, rows: list[dict]) -> dict[str, Any]:
    """Nhóm 5: đúng bản tại event_date và không lẫn bản kia của cùng Điều.

    Bản kia của cùng Điều = Điều của dòng cùng câu hỏi nhưng khác văn bản trong nhóm 5.
    """
    g5 = [r for r in rows if r.get("group") == 5 and r.get("expected_provisions")]
    by_question: dict[str, set[str]] = defaultdict(set)
    for r in g5:
        by_question[r["question"].strip()] |= _provision_articles(r)
    ok = 0
    for r in g5:
        want = _provision_articles(r)
        others = by_question[r["question"].strip()] - want
        hits = search_nodes(db, r["question"], top_k=8, as_of=_as_of(r))
        got = {article_of(h["node_id"]) for h in hits}
        if want & got and not others & got:
            ok += 1
    return _rate(ok, len(g5), sum(1 for r in g5 if r.get("reviewed")))


def _injection_block(rows: list[dict]) -> dict[str, Any]:
    cases = [
        r for r in rows
        if r.get("group") == 3
        and ("injection" in f"{r.get('note') or ''} {r.get('source') or ''}".lower()
             or "chèn lệnh" in (r.get("note") or "").lower())
    ]
    ok = sum(1 for r in cases if looks_like_injection(r["question"]))
    return _rate(ok, len(cases), sum(1 for r in cases if r.get("reviewed")))


def _pii_leak() -> dict[str, Any]:
    leaks = 0
    for sentence, secrets in PII_CASES:
        flat = _squash(mask(sentence).text)
        leaks += sum(1 for s in secrets if _squash(s) in flat)
    return {"value": leaks, "n": len(PII_CASES), "n_reviewed": 0,
            "errors": leaks, "bound": round(3 / len(PII_CASES), 4) if not leaks else None}


def _upload_isolation(db: Session) -> dict[str, Any]:
    upload_ids = set(db.execute(
        text("SELECT doc_id FROM legal_document WHERE doc_type = 'upload'")
    ).scalars())
    bad = 0
    for q in UPLOAD_QUERIES:
        hits = search_nodes(db, q, top_k=5)
        bad += any(h["doc_id"] in upload_ids for h in hits)
    return {"value": bad == 0, "n": len(UPLOAD_QUERIES), "n_reviewed": 0,
            "errors": bad, "bound": round(3 / len(UPLOAD_QUERIES), 4) if not bad else None}


def run_gate(db: Session, rows: list[dict] | None = None) -> dict[str, Any]:
    rows = load_golden() if rows is None else rows
    answer_rows = [
        r for r in rows if r.get("expected_action") == "answer" and r.get("expected_provisions")
    ]
    return {
        "recall@5": _retrieval_metric(db, answer_rows, 5),
        "recall@8": _retrieval_metric(db, answer_rows, 8),
        "mrr": _mrr(db, answer_rows),
        "version_correct": _version_correct(db, rows),
        "injection_block": _injection_block(rows),
        "pii_leak": _pii_leak(),
        "upload_isolation": _upload_isolation(db),
    }


def _metrics(baseline: dict[str, Any] | None) -> dict[str, Any]:
    """Chấp nhận cả file baseline (có khoá metrics) lẫn riêng phần metrics."""
    if not baseline:
        return {}
    return baseline.get("metrics") or baseline


def compare(current: dict[str, Any], baseline: dict[str, Any] | None) -> list[str]:
    """Danh sách lỗi cổng. Chuỗi rỗng nghĩa là đạt."""
    base = _metrics(baseline)
    fails: list[str] = []

    for name in ("recall@5", "recall@8", "mrr"):
        cur, old = current.get(name) or {}, base.get(name) or {}
        if cur.get("value") is None or old.get("value") is None:
            continue
        if cur["value"] < old["value"] - TOLERANCE:
            fails.append(f"{name} tụt: {cur['value']:.3f} < {old['value']:.3f} - {TOLERANCE}")

    vc = current.get("version_correct") or {}
    if vc.get("n") and (vc.get("value") or 0.0) < 1.0:
        fails.append(
            f"version_correct {vc.get('value')} < 1.0 ({vc.get('errors')}/{vc.get('n')} ca sai)"
        )

    inj, old_inj = current.get("injection_block") or {}, base.get("injection_block") or {}
    if inj.get("n") and old_inj.get("value") is not None and (inj.get("value") or 0.0) < old_inj["value"]:
        fails.append(f"injection_block tụt: {inj.get('value')} < baseline {old_inj['value']}")

    pii = current.get("pii_leak") or {}
    if pii.get("value"):
        fails.append(f"pii_leak = {pii['value']} > 0")

    if not (current.get("upload_isolation") or {}).get("value"):
        fails.append("upload_isolation = false")
    return fails


def baseline_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = "unknown"
    return {
        "date": date.today().isoformat(),
        "commit": commit,
        "n": {k: v.get("n") for k, v in metrics.items()},
        "metrics": metrics,
    }
