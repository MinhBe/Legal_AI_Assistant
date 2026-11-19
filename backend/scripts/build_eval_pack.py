"""Gói đánh giá golden set để chấm mô hình TRÊN KAGGLE (Minh 19/11/2026: so sánh mô hình chạy trên
Kaggle, máy nhà chỉ nhận mô hình thắng).

Máy nhà chỉ làm phần nhẹ: truy hồi (vector, không rerank) + dựng đúng messages mà
`answer_with_citations` gửi cho mô hình. Kaggle sinh câu trả lời bằng base / base+LoRA và chấm như
scripts/ft_eval.py (trích dẫn đúng điều, trích dẫn sai phiên bản, JSON hợp lệ).

    docker compose exec api python -m scripts.build_eval_pack --out data/finetune/eval_pack.jsonl
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from app.agent import qa
from app.agent.followup import history_block
from app.amend import timeframe
from app.db.base import SessionLocal
from app.rag.domain import classify
from app.rag.search import search_nodes
from scripts.ft_eval import load_rows, version_map


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/finetune/eval_pack.jsonl")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    rows = load_rows(args.limit)
    db = SessionLocal()
    out = []
    try:
        for row in rows:
            msg = row["question"]
            today = date.today()
            event, _g = timeframe.extract_event_date(msg, today)
            hits = search_nodes(db, msg, top_k=8, as_of=event, rerank=False, domains=classify(msg))
            tf = qa._timeframe(db, event, today, msg)  # noqa: SLF001 — đúng như pipeline
            convo = history_block(row.get("history"))
            messages = qa._answer_messages(  # noqa: SLF001
                hits, convo, msg, timeframe_lines=timeframe.summary_lines(tf)) if hits else []
            ids = [h["node_id"] for h in hits]
            versions = {k: [str(v[0]) if v[0] else None, str(v[1]) if v[1] else None]
                        for k, v in version_map(db, ids).items()}
            out.append({
                "id": row["id"], "question": msg, "messages": messages, "hit_ids": ids,
                "expected": [p["node_id"] for p in row.get("expected_provisions") or []
                             if p.get("node_id")],
                "effective": row.get("event_date") or row["advice_date"], "versions": versions,
            })
    finally:
        db.close()
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in out) + "\n",
                    encoding="utf-8")
    print(f"{len(out)} câu, {sum(1 for r in out if r['messages'])} có căn cứ truy hồi -> {path}")


if __name__ == "__main__":
    main()
