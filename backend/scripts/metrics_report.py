"""Báo cáo số đo từ data/metrics/*.jsonl: độ trễ, token, số lời gọi, tỉ lệ thắng theo model.

    docker compose exec api python -m scripts.metrics_report [--since 2026-11-05T00:00] [--kind chat|eval] [--tag ...]

Đọc requests.jsonl và llm_calls.jsonl (và llm_winners.jsonl qua cờ won trong llm_calls).
"""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path

DIR = Path("/app/data/metrics")


def _load(name: str) -> list[dict]:
    p = DIR / name
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _pct(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None)
    ap.add_argument("--kind", default=None, choices=["chat", "eval"])
    ap.add_argument("--tag", default=None, help="chỉ tính request có tag này (chỉ có ở kind=eval)")
    args = ap.parse_args()

    reqs = _load("requests.jsonl")
    calls = _load("llm_calls.jsonl")
    if args.since:
        reqs = [r for r in reqs if r.get("ts", "") >= args.since]
        calls = [c for c in calls if c.get("ts", "") >= args.since]
    if args.kind:
        reqs = [r for r in reqs if r.get("kind") == args.kind]
    if args.tag:
        reqs = [r for r in reqs if r.get("tag") == args.tag]
    ids = {r["request_id"] for r in reqs}
    calls = [c for c in calls if c.get("request_id") in ids]
    # cờ "thắng" được ghi riêng (mark_winner) vì bản ghi lời gọi đã ghi trước khi biết ai thắng
    winners = {w["call_id"] for w in _load("llm_winners.jsonl") if w.get("request_id") in ids}
    for c in calls:
        c["won"] = c.get("call_id") in winners

    print(f"Số request: {len(reqs)}   số lời gọi LLM: {len(calls)}")
    if not reqs:
        print("Không có dữ liệu. Kiểm tra /app/data/metrics và tham số lọc.")
        return

    total = [r["total_s"] for r in reqs if r.get("total_s") is not None]
    ttft = [r["ttft_s"] for r in reqs if r.get("ttft_s") is not None]
    print(f"total_s  p50={_pct(total, 50)}  p95={_pct(total, 95)}")
    print(f"ttft_s   p50={_pct(ttft, 50)}  p95={_pct(ttft, 95)}  (n={len(ttft)})")

    ta = [r["tokens_all"] for r in reqs if r.get("tokens_all") is not None]
    tw = [r["tokens_winners"] for r in reqs if r.get("tokens_winners") is not None]
    ro = [r["race_overhead"] for r in reqs if r.get("race_overhead") is not None]
    print(f"token/request: tất cả trung bình={statistics.fmean(ta) if ta else None:.0f}  "
          f"của người thắng trung bình={statistics.fmean(tw) if tw else None:.0f}  "
          f"race_overhead trung bình={statistics.fmean(ro) if ro else None}")

    per_req_calls = [r["n_llm_calls"] for r in reqs if r.get("n_llm_calls") is not None]
    errs = sum(1 for c in calls if c.get("error"))
    attempts = sum(c.get("attempts", 1) or 1 for c in calls)
    print(f"lời gọi/request trung bình={statistics.fmean(per_req_calls) if per_req_calls else None:.2f}  "
          f"tỉ lệ lỗi={errs / len(calls):.3f}  tổng attempts={attempts}")

    by_model = defaultdict(lambda: {"calls": 0, "won": 0, "lat": []})
    for c in calls:
        key = f"{c.get('provider')}/{c.get('model')}"
        by_model[key]["calls"] += 1
        by_model[key]["won"] += 1 if c.get("won") else 0
        if not c.get("error"):
            by_model[key]["lat"].append(c["latency_s"])
    print("\nTheo model (lời gọi, tỉ lệ thắng, p50 độ trễ):")
    for key, v in sorted(by_model.items(), key=lambda kv: -kv[1]["calls"]):
        win_rate = v["won"] / v["calls"] if v["calls"] else 0
        print(f"  {key:45} n={v['calls']:4}  thắng={win_rate:.2f}  p50={_pct(v['lat'], 50)}")

    costs = [r["cost_ref_usd"] for r in reqs if r.get("cost_ref_usd") is not None]
    if costs and any(costs):
        mean = statistics.fmean(costs)
        print(f"\ncost_ref_usd trung bình/request={mean:.6f}  mỗi 1.000 request={mean * 1000:.4f} USD (giá tham chiếu)")
    else:
        print("\ncost_ref_usd: không tính được (LLM_PRICES_JSON để trống). Số token vẫn đúng.")

    est = sum(1 for c in calls if c.get("estimated"))
    rate = est / len(calls) if calls else 0
    print(f"\ndòng token ước lượng (estimated=True): {est}/{len(calls)} = {rate:.3f}")
    if rate > 0.10:
        print("CẢNH BÁO: trên 10% lời gọi có token ước lượng, số token chỉ là gần đúng.")


if __name__ == "__main__":
    main()
