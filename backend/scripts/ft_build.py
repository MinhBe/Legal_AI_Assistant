"""Dựng bộ dữ liệu fine-tune từ nguồn công khai (KG1).

    python -m scripts.ft_build --scope pilot --dry-run --out data/finetune/pilot
    python -m scripts.ft_build --scope pilot --pairs 3 --max-calls 60 --out data/finetune/pilot

`--dry-run` chỉ in số lời gọi Dahl và token ước lượng, KHÔNG gọi mô hình và không ghi tệp.
"""

from __future__ import annotations

import argparse
import json

from app.db.base import SessionLocal
from app.finetune import build


def main() -> None:
    ap = argparse.ArgumentParser(description="Dựng dữ liệu fine-tune (KG1) từ nguồn công khai")
    ap.add_argument("--scope", choices=list(build.SCOPES), default="pilot")
    ap.add_argument("--pairs", type=int, default=3)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-calls", type=int, default=60)
    ap.add_argument("--out", default="data/finetune/pilot")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        result = build.build_dataset(
            db,
            scope=args.scope,
            pairs=args.pairs,
            out=args.out,
            dry_run=args.dry_run,
            max_calls=args.max_calls,
            seed=args.seed,
        )
    finally:
        db.close()

    if args.dry_run:
        print(
            f"[dry-run] {result['calls']} lời gọi Dahl, ~{result['est_tokens']:,} token · "
            f"{result['records']} bản ghi ({result['skipped_no_text']} bỏ vì thiếu toàn văn, "
            f"{result['capped']} vượt --max-calls) · không ghi tệp"
        )
        return

    counts = result["counts"]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(
        f"Đã ghi {args.out}: train {counts['train']}, val {counts['val']}, "
        f"{result['dahl_calls']} lời gọi Dahl"
    )


if __name__ == "__main__":
    main()
