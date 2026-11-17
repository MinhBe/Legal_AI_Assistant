"""Đo mô hình trong máy trước/sau fine-tune trên golden set (KG1).

    docker compose exec api python -m scripts.ft_eval \
        --model qwen2.5:7b --model lawvn-qwen7b-ft --limit 20

Chạy đúng pipeline `answer_with_citations`, đổi LOCAL_MODEL theo từng mô hình và tắt tuyến
đám mây để so công bằng. Ghi `data/finetune/eval-<ngày>.json`.

Cổng thay mô hình: mô hình fine-tune chỉ được thay mô hình hiện tại khi tỉ lệ trích dẫn đúng
KHÔNG thấp hơn và số trích dẫn sai phiên bản KHÔNG cao hơn.
"""

from __future__ import annotations

import argparse
import json
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.config import get_settings
from app.db.base import SessionLocal
from app.llm import router as router_mod
from app.obs import metrics
from app import prompts

GOLDEN = Path(__file__).resolve().parents[1] / "eval" / "golden_v2.jsonl"
OUT_DIR = Path("data/finetune")


def load_rows(limit: int | None, path: Path | None = None) -> list[dict]:
    p = path or GOLDEN
    rows = [
        json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    rows = [r for r in rows if r.get("expected_provisions")]
    return rows[:limit] if limit else rows


def article_of(node_id: str) -> str:
    return "-".join(node_id.split("-")[:2])


def citation_hit(row: dict, citations: list[str]) -> bool:
    want = {p["node_id"] for p in row.get("expected_provisions") or [] if p.get("node_id")}
    if not want:
        return False
    articles = {article_of(n) for n in want}
    return any(c in want or article_of(c) in articles for c in citations)


def version_map(db, node_ids: list[str]) -> dict[str, tuple[date | None, date | None]]:
    if not node_ids:
        return {}
    rows = db.execute(
        text(
            "SELECT provision_key, valid_from, valid_to FROM provision_version "
            "WHERE provision_key = ANY(:ids)"
        ),
        {"ids": node_ids},
    ).mappings()
    return {r["provision_key"]: (r["valid_from"], r["valid_to"]) for r in rows}


class _LocalSettings:
    """Bản sao settings chỉ dùng Ollama với một mô hình (không mượn đám mây khi so sánh)."""

    def __init__(self, base, model: str) -> None:
        self._base = base
        self.local_model = model
        self.llm_legacy_race = False

    def cloud_route(self):
        return None

    def __getattr__(self, name: str):
        return getattr(self._base, name)


@contextmanager
def local_only(model: str):
    base = get_settings()
    old = router_mod.settings
    router_mod.settings = _LocalSettings(base, model)
    try:
        yield
    finally:
        router_mod.settings = old


def run_model(model: str, rows: list[dict], db) -> dict[str, Any]:
    from app.agent import qa

    counts = {"json_ok": 0, "json_bad": 0}
    orig_parse = qa.parse_json

    def counting_parse(raw: str):
        try:
            data = orig_parse(raw)
        except Exception:
            counts["json_bad"] += 1
            raise
        counts["json_ok"] += 1
        return data

    hits, wrong, verifier_problems = 0, 0, 0
    latencies: list[float] = []
    per_row: list[tuple[dict, list[str]]] = []
    qa.parse_json = counting_parse
    try:
        with local_only(model):
            for row in rows:
                citations: list[str] = []
                t0 = time.monotonic()
                ctx = metrics.start_request(
                    "eval", tag="ft_eval", gold_id=row["id"],
                    prompt_version=prompts.active_version("qa_answer"),
                )
                try:
                    for ev, data in metrics.traced(
                        qa.answer_with_citations(row["question"], row.get("history")), ctx
                    ):
                        if ev == "citation":
                            citations.append(data["node_id"])
                        elif ev == "verifier" and (not data.get("ok") or data.get("dropped")):
                            verifier_problems += 1
                except Exception:  # noqa: BLE001 — một câu lỗi vẫn phải được đếm
                    verifier_problems += 1
                latencies.append(time.monotonic() - t0)
                hits += int(citation_hit(row, citations))
                per_row.append((row, citations))
    finally:
        qa.parse_json = orig_parse

    versions = version_map(db, sorted({c for _, cites in per_row for c in cites}))
    for row, citations in per_row:
        effective = date.fromisoformat(row.get("event_date") or row["advice_date"])
        for cid in citations:
            _from, to = versions.get(cid, (None, None))
            if to is not None and effective >= to:
                wrong += 1

    n = len(rows)
    parsed = counts["json_ok"] + counts["json_bad"]
    return {
        "model": model,
        "rows": n,
        "citation_hit_rate": round(hits / n, 3) if n else 0.0,
        "wrong_version": wrong,
        "json_validity": round(counts["json_ok"] / parsed, 3) if parsed else 1.0,
        "verifier_problems": verifier_problems,
        "avg_latency_s": round(sum(latencies) / n, 2) if n else 0.0,
    }


def gate(base: dict, candidate: dict) -> dict[str, Any]:
    """Mô hình fine-tune chỉ được thay mô hình hiện tại khi không thua ở hai chỉ số chính."""
    ok = (
        candidate["citation_hit_rate"] >= base["citation_hit_rate"]
        and candidate["wrong_version"] <= base["wrong_version"]
    )
    return {"base": base["model"], "candidate": candidate["model"], "ok": ok}


def _print(results: list[dict]) -> None:
    print(f"{'mô hình':<26}{'hit':>7}{'sai bản':>9}{'JSON':>7}{'Verifier':>10}{'giây':>7}")
    for r in results:
        print(
            f"{r['model']:<26}{r['citation_hit_rate']:>7.3f}{r['wrong_version']:>9}"
            f"{r['json_validity']:>7.3f}{r['verifier_problems']:>10}{r['avg_latency_s']:>7.2f}"
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Đo mô hình local trên golden set (KG1)")
    ap.add_argument("--model", action="append", required=True, help="lặp lại cho mỗi mô hình")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--golden", default=None, help="tệp golden khác (mặc định eval/golden_v2.jsonl)")
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    args = ap.parse_args()

    rows = load_rows(args.limit, Path(args.golden) if args.golden else None)
    if not rows:
        raise SystemExit("không có câu hỏi vàng nào kèm điều khoản mong đợi")
    db = SessionLocal()
    try:
        results = [run_model(m, rows, db) for m in args.model]
    finally:
        db.close()

    gates = [gate(results[0], r) for r in results[1:]]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"eval-{datetime.now():%Y-%m-%d}.json"
    payload = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "limit": args.limit,
        "rows": len(rows),
        "gate_rule": "citation_hit_rate >= mô hình hiện tại và wrong_version <= mô hình hiện tại",
        "models": {r["model"]: r for r in results},
        "gates": gates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _print(results)
    for g in gates:
        verdict = "ĐƯỢC thay" if g["ok"] else "KHÔNG được thay"
        print(f"{g['candidate']} so với {g['base']}: {verdict}")
    print(f"Đã ghi {path}")


if __name__ == "__main__":
    main()
