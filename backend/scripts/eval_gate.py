"""Cổng đánh giá G4 — đo cục bộ, không gọi LLM.

    python -m scripts.eval_gate                     # chạy cổng, exit 1 nếu có lỗi
    python -m scripts.eval_gate --update-baseline   # ghi eval/gate_baseline.json
    python -m scripts.eval_gate --json              # in JSON cho máy đọc
"""

from __future__ import annotations

import argparse
import json
import sys

from app.db.base import SessionLocal
from app.eval.gate import BASELINE, baseline_payload, compare, run_gate


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    return f"{v:.3f}"


def _bad(name: str, m: dict) -> bool:
    if name == "pii_leak":
        return bool(m.get("value"))
    if name == "upload_isolation":
        return not m.get("value")
    if name == "version_correct":
        return bool(m.get("n")) and (m.get("value") or 0) < 1.0
    return False


def _table(metrics: dict) -> str:
    lines = [f"{'chỉ số':<17}{'giá trị':>9}{'n':>5}{'duyệt':>7}{'lỗi':>6}{'3/n':>7}  trạng thái"]
    for name, m in metrics.items():
        status = "FAIL" if _bad(name, m) else "OK"
        lines.append(
            f"{name:<17}{_fmt(m.get('value')):>9}{m.get('n', 0):>5}{m.get('n_reviewed', 0):>7}"
            f"{_fmt(m.get('errors')):>6}{_fmt(m.get('bound')):>7}  {status}"
        )
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--update-baseline", action="store_true", help="ghi lại baseline")
    ap.add_argument("--json", action="store_true", help="in JSON")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        metrics = run_gate(db)
    finally:
        db.close()

    if args.update_baseline:
        payload = baseline_payload(metrics)
        BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        if args.json:
            print(json.dumps(payload, ensure_ascii=False))
        else:
            print(_table(metrics))
            print(f"\nĐã ghi baseline: {BASELINE}")
        return

    baseline = json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else None
    if baseline is None:
        failures = [f"chưa có baseline {BASELINE}; chạy --update-baseline trước"]
    else:
        failures = compare(metrics, baseline)

    if args.json:
        print(json.dumps({"metrics": metrics, "failures": failures}, ensure_ascii=False))
    else:
        print(_table(metrics))
        for f in failures:
            print(f"FAIL: {f}")
        print("\nCổng: ĐẠT" if not failures else "\nCổng: KHÔNG ĐẠT")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
