"""Đo truy hồi (`retrieval`) và hỏi đáp đầu-cuối (`e2e`) trên gold set 50 câu.

    docker compose exec api python -m scripts.eval_gold --mode retrieval --tag ten --commit <hash>
    docker compose exec api python -m scripts.eval_gold --mode e2e --repeat 3 --tag ten --commit <hash>

Xem backend/eval/gold_v1.jsonl (định dạng) và docs/ke-hoach-V1-V5.md mục V1.4 (đặc tả đầy đủ).
"""

from __future__ import annotations

import argparse
import inspect
import json
import statistics
import sys
import time
from datetime import UTC, date, datetime
from functools import partial
from pathlib import Path
from typing import Any

from app.agent.followup import search_with_history
from app.agent.qa import REFUSAL
from app.config import get_settings
from app.db.base import SessionLocal
from app.rag.search import search_nodes

GOLD = Path(__file__).resolve().parents[1] / "eval" / "gold_v1.jsonl"
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"
RESULTS_MD = Path(__file__).resolve().parents[1] / "eval" / "RESULTS.md"


def article_of(node_id: str) -> str:
    return "-".join(node_id.split("-")[:2])


def load_gold(only: list[str] | None = None) -> list[dict]:
    rows = [json.loads(line) for line in GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]
    if any(not r["reviewed"] for r in rows):
        n = sum(1 for r in rows if not r["reviewed"])
        print(f"\033[31mCẢNH BÁO: {n} câu chưa duyệt (reviewed=false)\033[0m", file=sys.stderr)
    if only:
        prefixes = tuple(only)
        rows = [r for r in rows if r["id"].rstrip("0123456789") in prefixes or r["category"] in prefixes]
    return rows


def pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    k = min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))
    return xs[k]


# ── retrieval ─────────────────────────────────────────────────────────────────

def _search(db, query: str, *, top_k: int, mode: str | None, rerank: bool | None, as_of: date | None = None):
    """search_nodes trước V2 chưa có tham số mode/rerank; chỉ truyền khi hàm nhận được.
    Chữ ký khớp `search_nodes`/`search_with_history` (đều dùng từ khoá `top_k`)."""
    kw: dict[str, Any] = {"top_k": top_k}
    if as_of is not None:
        kw["as_of"] = as_of
    sig = inspect.signature(search_nodes)
    if mode is not None and "mode" in sig.parameters:
        kw["mode"] = mode
    if rerank is not None and "rerank" in sig.parameters:
        kw["rerank"] = rerank
    return search_nodes(db, query, **kw)


def run_retrieval(rows: list[dict], *, k: int, mode: str | None, rerank: bool | None) -> dict:
    """Chấm điểm truy hồi trên `rows`. Dùng lại được từ sweep_retrieval.py (V2.7)."""
    db = SessionLocal()
    per_row = []
    try:
        for r in rows:
            if r["expect"] == "refuse":
                continue  # nhóm E không có đáp án truy hồi
            t0 = time.monotonic()
            if r.get("history"):
                hits = search_with_history(
                    db, r["question"], r["history"], top_k=k,
                    search=partial(_search, mode=mode, rerank=rerank),
                )
            else:
                hits = _search(db, r["question"], top_k=k, mode=mode, rerank=rerank)
            latency_ms = (time.monotonic() - t0) * 1000
            got_articles = [article_of(h["node_id"]) for h in hits]
            rank = next((i + 1 for i, a in enumerate(got_articles) if a in r["expected_articles"]), None)

            row_out = {
                "id": r["id"], "category": r["category"], "rank": rank,
                "hit@1": rank == 1, "hit@3": rank is not None and rank <= 3,
                "hit@k": rank is not None, "rr": (1 / rank) if rank else 0.0,
                "latency_ms": round(latency_ms, 1),
            }
            if r["category"] == "nhieu_van_de":
                want = set(r["expected_articles"])
                row_out["recall"] = len(want & set(got_articles)) / len(want) if want else None
            per_row.append(row_out)

            if r["category"] == "thoi_diem" and r.get("as_of"):
                t0 = time.monotonic()
                hits2 = _search(db, r["question"], top_k=k, mode=mode, rerank=rerank,
                                 as_of=date.fromisoformat(r["as_of"]))
                lat2 = (time.monotonic() - t0) * 1000
                got2 = [article_of(h["node_id"]) for h in hits2]
                want2 = r["expected_articles_as_of"] or []
                rank2 = next((i + 1 for i, a in enumerate(got2) if a in want2), None)
                per_row.append({
                    "id": r["id"] + "-as_of", "category": "thoi_diem_as_of", "rank": rank2,
                    "hit@1": rank2 == 1, "hit@3": rank2 is not None and rank2 <= 3,
                    "hit@k": rank2 is not None, "rr": (1 / rank2) if rank2 else 0.0,
                    "latency_ms": round(lat2, 1),
                })
    finally:
        db.close()

    return {"rows": per_row, "summary": summarize_retrieval(per_row)}


def _agg_retrieval(items: list[dict]) -> dict:
    n = len(items)
    lat = [x["latency_ms"] for x in items]
    return {
        "n": n,
        "hit@1": round(sum(x["hit@1"] for x in items) / n, 3) if n else None,
        "hit@3": round(sum(x["hit@3"] for x in items) / n, 3) if n else None,
        "hit@k": round(sum(x["hit@k"] for x in items) / n, 3) if n else None,
        "mrr": round(sum(x["rr"] for x in items) / n, 3) if n else None,
        "p50_ms": round(pct(lat, 50), 1) if lat else None,
        "p95_ms": round(pct(lat, 95), 1) if lat else None,
    }


def summarize_retrieval(per_row: list[dict]) -> dict:
    by_cat = {}
    for cat in sorted({x["category"] for x in per_row}):
        by_cat[cat] = _agg_retrieval([x for x in per_row if x["category"] == cat])
    return {"overall": _agg_retrieval(per_row), "by_category": by_cat}


# ── e2e ───────────────────────────────────────────────────────────────────────

def _patch_anti_cache(run_id: str, rep: int):
    """Nối mã lượt vào cuối message user để Dahl không trả lời từ cache khi --repeat>1.
    Trả về hàm gỡ lại (restore)."""
    from app.agent import qa

    orig = qa._answer_messages
    tag = f"\n(Mã lượt đánh giá: {run_id}-{rep})"

    def wrapped(hits, convo, message):
        msgs = orig(hits, convo, message)
        msgs[-1]["content"] += tag
        return msgs

    qa._answer_messages = wrapped
    return lambda: setattr(qa, "_answer_messages", orig)


def _run_one_e2e(r: dict) -> dict:
    from app.agent.qa import answer_with_citations

    t0 = time.monotonic()
    ttft_s = None
    citations: list[str] = []
    refused_cue = False
    escalate = False
    error = None
    try:
        for ev, data in answer_with_citations(r["question"], r.get("history")):
            if ev == "token":
                if ttft_s is None:
                    ttft_s = time.monotonic() - t0
                if REFUSAL[:20] in data.get("text", ""):
                    refused_cue = True
            elif ev == "citation":
                citations.append(data["node_id"])
            elif ev == "suggest_rewrite":
                refused_cue = True
            elif ev == "done":
                if data.get("escalate"):
                    escalate = True
            elif ev == "error":
                error = data.get("message")
    except Exception as exc:  # noqa: BLE001 — câu lỗi vẫn phải được đếm, không làm vỡ cả lượt chạy
        error = str(exc)[:300]

    refused = not citations and (refused_cue or escalate)
    got_articles = {article_of(c) for c in citations}
    if r["expect"] == "refuse":
        correct = refused
    else:
        correct = bool(got_articles & set(r["expected_articles"]))
    clause_ok = None
    if r["expected_nodes"]:
        clause_ok = any(c.startswith(tuple(r["expected_nodes"])) for c in citations)
    wrong_version = any(c.startswith("blld2012") for c in citations) if r["category"] == "thoi_diem" else None

    return {
        "id": r["id"], "category": r["category"], "error": error,
        "refused": refused, "correct": correct if error is None else None,
        "clause_ok": clause_ok, "wrong_version": wrong_version,
        "citations": citations, "latency_s": round(time.monotonic() - t0, 2),
        "ttft_s": round(ttft_s, 2) if ttft_s is not None else None,
    }


def run_e2e(rows: list[dict], *, repeat: int, run_id: str) -> dict:
    per_row = []
    n_error = 0
    for r in rows:
        reps = []
        for rep in range(repeat):
            restore = _patch_anti_cache(run_id, rep) if repeat > 1 else (lambda: None)
            try:
                reps.append(_run_one_e2e(r))
            finally:
                restore()
        n_error += sum(1 for x in reps if x["error"])
        oks = [x for x in reps if x["error"] is None]
        pass_any = any(x["correct"] for x in oks) if oks else False
        pass_all = all(x["correct"] for x in oks) if oks else False
        cited_sets = [frozenset(x["citations"]) for x in oks]
        consistent = len(set(cited_sets)) <= 1 if cited_sets else None
        per_row.append({
            "id": r["id"], "category": r["category"], "repeat": repeat,
            "reps": reps, "pass_any": pass_any, "pass_all": pass_all, "consistent": consistent,
        })
        status = "OK" if pass_any else ("REFUSED-OK" if r["expect"] == "refuse" and pass_any else "MISS")
        print(f"  [{r['id']:5}] {status:9} lat={reps[0]['latency_s']:>5.1f}s "
              f"cites={reps[0]['citations'][:2]}", flush=True)

    total = len(rows) * repeat
    if total and n_error / total > 0.2:
        print(f"\033[31mLỗi {n_error}/{total} (>20%). Dừng lại — chạy lại bằng --resume.\033[0m",
              file=sys.stderr)

    gold_by_id = {r["id"]: r for r in rows}
    return {"rows": per_row, "summary": summarize_e2e(per_row, gold_by_id)}


def summarize_e2e(per_row: list[dict], gold_by_id: dict[str, dict]) -> dict:
    def rate(key: str) -> float:
        oks = [x for x in per_row if any(rp["error"] is None for rp in x["reps"])]
        if not oks:
            return 0.0
        return round(sum(1 for x in oks if x[key]) / len(oks), 3)

    n_error = sum(1 for x in per_row for rp in x["reps"] if rp["error"])
    refusal_rows = [x for x in per_row if any(rp["error"] is None for rp in x["reps"])
                     and gold_by_id[x["id"]]["expect"] == "refuse"]
    clause_rows = [rp for x in per_row for rp in x["reps"] if rp["clause_ok"] is not None]
    return {
        "n": len(per_row), "n_errors": n_error, "pass_any_rate": rate("pass_any"),
        "pass_all_rate": rate("pass_all"),
        "refuse_correct_rate": (round(sum(1 for x in refusal_rows if x["pass_any"]) / len(refusal_rows), 3)
                                 if refusal_rows else None),
        "clause_ok_rate": (round(sum(1 for rp in clause_rows if rp["clause_ok"]) / len(clause_rows), 3)
                            if clause_rows else None),
        "avg_latency_s": round(statistics.fmean(
            rp["latency_s"] for x in per_row for rp in x["reps"] if rp["error"] is None), 2)
            if any(rp["error"] is None for x in per_row for rp in x["reps"]) else None,
    }


# ── điểm vào ──────────────────────────────────────────────────────────────────

def apply_overrides(pairs: list[str]) -> dict:
    settings = get_settings()
    applied = {}
    for kv in pairs:
        k, _, v = kv.partition("=")
        cur = getattr(settings, k)
        if isinstance(cur, bool):
            v2 = v.lower() in ("1", "true", "yes")
        elif isinstance(cur, int):
            v2 = int(v)
        elif isinstance(cur, float):
            v2 = float(v)
        else:
            v2 = v
        setattr(settings, k, v2)
        applied[k] = v2
    return applied


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["retrieval", "e2e"], required=True)
    ap.add_argument("--search", choices=["vector", "bm25", "hybrid"], default=None)
    ap.add_argument("--rerank", type=int, choices=[0, 1], default=None)
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--prompt-version", default=None)
    ap.add_argument("--only", default=None, help="vd: A,B hoặc tra_cuu,nghi_dinh")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--commit", default="unknown")
    ap.add_argument("--resume", default=None)
    ap.add_argument("--set", dest="set_", nargs="*", default=[])
    args = ap.parse_args()

    only = args.only.split(",") if args.only else None
    all_rows = load_gold(only)
    if args.limit:
        all_rows = all_rows[: args.limit]

    applied = apply_overrides(args.set_)
    if args.prompt_version:
        get_settings().qa_prompt_version = args.prompt_version  # no-op trước V4, giữ cho tương thích

    rerank = None if args.rerank is None else bool(args.rerank)
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    settings = get_settings()

    # --resume: nạp file cũ, bỏ qua id đã có kết quả không lỗi, ghi đè vào cùng file.
    old_rows: list[dict] = []
    rows = all_rows
    out_path = None
    if args.resume:
        out_path = Path(args.resume)
        old = json.loads(out_path.read_text(encoding="utf-8"))
        old_rows = old["rows"]
        if args.mode == "retrieval":
            done_ids = {x["id"] for x in old_rows}  # retrieval không lỗi cục bộ theo câu
        else:
            done_ids = {x["id"] for x in old_rows if all(rp["error"] is None for rp in x["reps"])}
        rows = [r for r in all_rows if r["id"] not in done_ids]
        old_rows = [x for x in old_rows if x["id"] not in {r["id"] for r in rows}]
        print(f"--resume: {len(done_ids)} câu đã xong, chạy lại {len(rows)} câu còn lại")

    t0 = time.monotonic()
    if not rows:
        result = {"rows": [], "summary": None}
    elif args.mode == "retrieval":
        result = run_retrieval(rows, k=args.k, mode=args.search, rerank=rerank)
    else:
        result = run_e2e(rows, repeat=args.repeat, run_id=run_id)
    elapsed = round(time.monotonic() - t0, 1)

    merged_rows = old_rows + result["rows"]
    if old_rows:
        gold_by_id = {r["id"]: r for r in all_rows}
        result = {
            "rows": merged_rows,
            "summary": (summarize_retrieval(merged_rows) if args.mode == "retrieval"
                        else summarize_e2e(merged_rows, gold_by_id)),
        }

    default_search_mode = getattr(settings, "search_mode", "vector")  # search_mode: thêm ở V2.2
    meta = {
        "mode": args.mode, "search": args.search or default_search_mode,
        "rerank": rerank if rerank is not None else getattr(settings, "rerank_enabled", False),
        "k": args.k, "repeat": args.repeat, "prompt_version": args.prompt_version or "v1",
        "embedder": settings.embedder, "overrides": applied, "commit": args.commit,
        "n_rows_in_gold": len(all_rows), "n_unreviewed": sum(1 for r in all_rows if not r["reviewed"]),
        "tag": args.tag, "ts": datetime.now(UTC).isoformat(), "elapsed_s": elapsed,
    }
    out = {"meta": meta, **result}

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    if out_path is None:   # không phải --resume: file mới
        out_path = RESULTS_DIR / f"{run_id}_{args.tag}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    s = result["summary"]
    if args.mode == "retrieval":
        ov = s["overall"]
        line = (f"| {run_id} | {args.tag} | retrieval | {meta['search']} | {meta['rerank']} | "
                f"{meta['prompt_version']} | {ov['hit@1']} | {ov['hit@k']} | {ov['mrr']} | — | — | "
                f"{ov['p95_ms']} | {args.commit} |")
        print(f"\n=== {args.tag} (retrieval, {elapsed}s) ===")
        print(f"hit@1={ov['hit@1']} hit@{args.k}={ov['hit@k']} MRR={ov['mrr']} p95={ov['p95_ms']}ms")
        for cat, a in result["summary"]["by_category"].items():
            print(f"  {cat:20} n={a['n']:3} hit@1={a['hit@1']} hit@{args.k}={a['hit@k']} MRR={a['mrr']}")
    else:
        line = (f"| {run_id} | {args.tag} | e2e | — | — | {meta['prompt_version']} | — | — | — | "
                f"{s['pass_any_rate']} | {s['refuse_correct_rate']} | — | {args.commit} |")
        print(f"\n=== {args.tag} (e2e, {elapsed}s) ===")
        print(f"pass_any={s['pass_any_rate']} pass_all={s['pass_all_rate']} "
              f"từ_chối_đúng={s['refuse_correct_rate']} clause_ok={s['clause_ok_rate']} "
              f"lỗi={s['n_errors']} latency_tb={s['avg_latency_s']}s")

    if not args.resume:  # lần chạy resume ghi tiếp vào out_path cũ, không thêm dòng mới vào RESULTS.md
        with RESULTS_MD.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        print(f"Nối 1 dòng vào: {RESULTS_MD}")
    print(f"\nGhi: {out_path}")


if __name__ == "__main__":
    main()
