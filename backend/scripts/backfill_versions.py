"""Dựng bảng phiên bản điều khoản (T1).

    docker compose exec api python -m scripts.backfill_versions
    docker compose exec api python -m scripts.backfill_versions --drop   # down migration

Chạy lại nhiều lần vẫn ra cùng số dòng: ba bảng chỉ do script này sinh ra.
"""

from __future__ import annotations

import argparse
import sys

from app.amend.versions import backfill, create_tables, drop_tables
from app.db.base import SessionLocal, engine


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drop", action="store_true", help="xoá ba bảng rồi thoát")
    args = ap.parse_args()

    if args.drop:
        drop_tables(engine)
        print("Đã xoá provision_version, transition_rule, legal_link.")
        return 0

    create_tables(engine)
    with SessionLocal() as db:
        counts = backfill(db)
        db.commit()

    for name, n in counts.items():
        print(f"{name:16s} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
