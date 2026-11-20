"""Ghi vector tạo trên Kaggle vào legal_node (tools/kaggle_embed.py gọi). Không nạp model trong máy.

    python -m scripts.apply_embeddings --dir data/embed_out

Đầu vào: <dir>/ids.json (danh sách node_id) và <dir>/vectors.npy (float32, đã chuẩn hoá, cùng thứ
tự). Chỉ ghi vào node đang có embedding NULL; tệp hàng đợi đã ghi xong chuyển sang
data/embed_queue/done/.
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import numpy as np
from sqlalchemy import text

from app.config import get_settings
from app.db.base import SessionLocal

QUEUE = Path("data/embed_queue")


def apply(out_dir: Path) -> dict:
    ids = json.loads((out_dir / "ids.json").read_text(encoding="utf-8"))
    vecs = np.load(out_dir / "vectors.npy")
    if len(ids) != len(vecs):
        raise SystemExit(f"lệch số dòng: {len(ids)} id, {len(vecs)} vector")
    if vecs.shape[1] != get_settings().embed_dim:
        raise SystemExit(f"sai số chiều: {vecs.shape[1]} (cần {get_settings().embed_dim})")
    db = SessionLocal()
    written = 0
    try:
        for i in range(0, len(ids), 500):
            batch = [{"id": n, "v": "[" + ",".join(f"{x:.7f}" for x in v) + "]"}
                     for n, v in zip(ids[i:i + 500], vecs[i:i + 500], strict=True)]
            res = db.execute(text("UPDATE legal_node SET embedding = CAST(:v AS vector) "
                                  "WHERE node_id = :id AND embedding IS NULL"), batch)
            written += res.rowcount or 0
        db.commit()
        left = db.execute(text("SELECT count(*) FROM legal_node WHERE embedding IS NULL")).scalar()
    finally:
        db.close()
    done_ids = set(ids)
    (QUEUE / "done").mkdir(parents=True, exist_ok=True)
    for q in QUEUE.glob("*.jsonl"):
        rows = [json.loads(x)["node_id"] for x in q.read_text(encoding="utf-8").splitlines() if x]
        if rows and all(r in done_ids for r in rows):
            shutil.move(str(q), QUEUE / "done" / q.name)
    return {"vectors": len(ids), "written": written, "null_left": left}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="data/embed_out")
    print(apply(Path(ap.parse_args().dir)))


if __name__ == "__main__":
    main()
