"""Nạp và kiểm tra golden set v2 (5 nhóm — design v1.1 §11.1).

Mỗi dòng là một JSON object; xem `eval/golden_schema.md`.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import bindparam, text

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden_v2.jsonl"
TARGETS = {1: 30, 2: 20, 3: 20, 4: 20, 5: 30}
ACTIONS = ("answer", "refuse", "escalate")


def load_golden(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path is not None else GOLDEN
    lines = p.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _bad_date(value) -> bool:
    if not isinstance(value, str):
        return True
    try:
        date.fromisoformat(value)
    except ValueError:
        return True
    return False


def validate(rows: list[dict], db=None) -> list[str]:
    """Trả về danh sách lỗi; rỗng nghĩa là hợp lệ. `db` là Session để kiểm node_id."""
    errors: list[str] = []
    seen: set[str] = set()
    for i, row in enumerate(rows):
        rid = row.get("id") or f"dòng {i + 1}"
        if rid in seen:
            errors.append(f"{rid}: trùng id")
        seen.add(rid)

        if row.get("group") not in TARGETS:
            errors.append(f"{rid}: nhóm không hợp lệ {row.get('group')!r}")
        if row.get("expected_action") not in ACTIONS:
            errors.append(f"{rid}: expected_action không hợp lệ {row.get('expected_action')!r}")
        for field in ("event_date", "advice_date"):
            value = row.get(field)
            if value is not None and _bad_date(value):
                errors.append(f"{rid}: {field} không phải ngày ISO: {value!r}")
        for prov in row.get("expected_provisions") or []:
            if not prov.get("node_id") or not prov.get("doc_id"):
                errors.append(f"{rid}: provision thiếu node_id/doc_id: {prov!r}")
        if row.get("expected_action") == "answer" and not row.get("expected_provisions"):
            errors.append(f"{rid}: câu 'answer' phải có expected_provisions")

    if db is not None:
        wanted = {
            prov["node_id"]
            for row in rows
            for prov in row.get("expected_provisions") or []
            if prov.get("node_id")
        }
        if wanted:
            stmt = text("SELECT node_id FROM legal_node WHERE node_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            )
            found = set(db.execute(stmt, {"ids": sorted(wanted)}).scalars())
            for missing in sorted(wanted - found):
                errors.append(f"node_id không có trong legal_node: {missing}")
    return errors


def group_counts(rows: list[dict]) -> dict[int, int]:
    counts = Counter(row.get("group") for row in rows)
    return {group: counts.get(group, 0) for group in sorted(TARGETS)}
