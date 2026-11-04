"""In văn bản các Điều ứng viên để viết gold set (không gọi LLM).

    docker compose exec api python -m scripts.make_gold_candidates

Ghi ra eval/candidates.md (không commit — xem .gitignore). File này chỉ để người
viết gold set đọc nhanh nội dung thật của các Điều trước khi đặt câu hỏi.
"""

from __future__ import annotations

import random
from pathlib import Path

from sqlalchemy import text

from app.db.base import SessionLocal

OUT = Path("eval/candidates.md")
random.seed(42)


def _format_article(db, a) -> list[str]:
    kids = db.execute(
        text("SELECT node_id, text FROM legal_node WHERE node_id=:a OR parent_id=:a ORDER BY seq"),
        {"a": a.node_id},
    ).all()
    lines = [f"## {a.node_id} — {a.heading} (Chương {a.chapter_no})\n"]
    lines += [f"- `{k.node_id}`: {k.text[:400]}" for k in kids]
    lines.append("")
    return lines


def main() -> None:
    db = SessionLocal()
    arts = db.execute(
        text(
            "SELECT node_id, doc_id, article_no, heading, chapter_no FROM legal_node "
            "WHERE level='article' AND doc_id IN ('blld2019','nd145_2020') ORDER BY seq"
        )
    ).all()
    by_doc: dict[str, list] = {}
    for a in arts:
        by_doc.setdefault(a.doc_id, []).append(a)
    pick = random.sample(by_doc["blld2019"], 30) + random.sample(by_doc["nd145_2020"], 8)

    lines: list[str] = ["# Ứng viên nhóm A/B (30 BLLĐ 2019 + 8 NĐ 145/2020, chọn ngẫu nhiên seed=42)\n"]
    for a in pick:
        lines += _format_article(db, a)

    # Nhóm C: cặp 2012 -> 2019 đổi nhiều nhất, xếp theo similarity tăng dần
    # (similarity thấp = nội dung khác nhau nhiều -> câu hỏi "trước/sau" có ý nghĩa).
    pairs = db.execute(
        text(
            "SELECT s.old_id, s.new_id, s.change_type, s.similarity, "
            "       o.heading AS old_heading, o.text AS old_text, "
            "       n.heading AS new_heading, n.text AS new_text "
            "FROM node_supersession s "
            "JOIN legal_node o ON o.node_id = s.old_id "
            "JOIN legal_node n ON n.node_id = s.new_id "
            "WHERE o.level = 'article' AND n.level = 'article' "
            "ORDER BY s.similarity ASC NULLS LAST LIMIT 10"
        )
    ).all()
    lines.append("\n# Ứng viên nhóm C (cặp Điều 2012 → 2019 đổi nhiều nhất, similarity thấp nhất)\n")
    for p in pairs:
        lines.append(f"## {p.old_id} -> {p.new_id}  (similarity={p.similarity}, {p.change_type})")
        lines.append(f"- 2012 `{p.old_id}` {p.old_heading}: {p.old_text[:400]}")
        lines.append(f"- 2019 `{p.new_id}` {p.new_heading}: {p.new_text[:400]}")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"Ghi {len(pick)} Điều (A/B) và {len(pairs)} cặp (C) vào {OUT}")


if __name__ == "__main__":
    main()
