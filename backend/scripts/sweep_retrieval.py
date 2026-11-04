"""Dò thông số truy hồi (hybrid) trên các nhóm dùng để dò, rồi kiểm tra trên nhóm giữ lại.

    docker compose exec api python -m scripts.sweep_retrieval --tag v2-sweep --commit <hash>

Theo kế hoạch V2.7: chỉ dò trên nhóm A, B, D (tra_cuu, nghi_dinh, nhieu_van_de). Nhóm C và F
(thoi_diem, noi_tiep) giữ riêng để kiểm tra cuối. Lưới 72 tổ hợp, không rerank. Rerank chỉ
thử trên 3 tổ hợp tốt nhất với rerank_top_n = 10 và 20.
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.config import get_settings
from scripts.eval_gold import load_gold, run_retrieval

DEV_CATS = ("tra_cuu", "nghi_dinh", "nhieu_van_de")
HOLDOUT_CATS = ("thoi_diem", "noi_tiep")
RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"

GRID = {
    "hybrid_candidates": [20, 30, 50],
    "rrf_k": [20, 60],
    "bm25_k1": [1.2, 1.5],
    "bm25_b": [0.5, 0.75],
    "k": [5, 8, 12],
}


def _set(settings, name: str, value) -> None:
    setattr(settings, name, value)


def _score(result: dict) -> tuple:
    o = result["summary"]  # đã là số tổng thể (overall) của một tổ hợp
    return (-o["hit@1"], -o["hit@k"], o["p95_ms"] or 0)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--commit", default="unknown")
    ap.add_argument("--tokenizer", default="underthesea", choices=["underthesea", "syllable"])
    args = ap.parse_args()

    settings = get_settings()
    settings.bm25_tokenizer = args.tokenizer
    dev = [r for r in load_gold() if r["category"] in DEV_CATS]
    holdout = [r for r in load_gold() if r["category"] in HOLDOUT_CATS]

    combos = [dict(zip(GRID, vals, strict=True)) for vals in itertools.product(*GRID.values())]
    print(f"Dò {len(combos)} tổ hợp trên {len(dev)} câu (nhóm {DEV_CATS})", flush=True)

    results = []
    for i, c in enumerate(combos, 1):
        for name, val in c.items():
            if name == "k":
                continue
            _set(settings, name, val)
        res = run_retrieval(dev, k=c["k"], mode="hybrid", rerank=False)
        results.append({"params": c, "summary": res["summary"]["overall"]})
        if i % 12 == 0:
            print(f"  {i}/{len(combos)}", flush=True)

    ranked = sorted(results, key=lambda x: _score(x))
    top = ranked[:3]

    # Rerank chỉ trên 3 tổ hợp đầu, với rerank_top_n 10 và 20
    rerank_runs = []
    for t in top:
        for n in (10, 20):
            for name, val in t["params"].items():
                if name != "k":
                    _set(settings, name, val)
            _set(settings, "rerank_top_n", n)
            res = run_retrieval(dev, k=t["params"]["k"], mode="hybrid", rerank=True)
            rerank_runs.append({"params": t["params"], "rerank_top_n": n, "summary": res["summary"]["overall"]})

    best = ranked[0]
    for name, val in best["params"].items():
        if name != "k":
            _set(settings, name, val)
    holdout_best = run_retrieval(holdout, k=best["params"]["k"], mode="hybrid", rerank=False)["summary"]["overall"]

    out = {
        "meta": {"tag": args.tag, "commit": args.commit, "tokenizer": args.tokenizer,
                 "dev_cats": list(DEV_CATS), "holdout_cats": list(HOLDOUT_CATS),
                 "n_dev": len(dev), "n_holdout": len(holdout), "grid": GRID,
                 "ts": datetime.now(UTC).isoformat()},
        "ranked": ranked,
        "rerank_top3": rerank_runs,
        "best_dev": best,
        "best_holdout": holdout_best,
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    path = RESULTS_DIR / f"{stamp}_{args.tag}_sweep.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\nTop 5 theo hit@1, rồi hit@k, rồi p95 (nhóm dò):")
    for r in ranked[:5]:
        o = r["summary"]
        print(f"  {r['params']}  hit@1={o['hit@1']} hit@k={o['hit@k']} mrr={o['mrr']} p95={o['p95_ms']}")
    print("\nRerank trên top 3:")
    for r in rerank_runs:
        o = r["summary"]
        print(f"  {r['params']} top_n={r['rerank_top_n']}  hit@1={o['hit@1']} hit@k={o['hit@k']} p95={o['p95_ms']}")
    print(f"\nNhóm giữ lại (C,F) với tổ hợp tốt nhất: {holdout_best}")
    print(f"\nGhi: {path}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
