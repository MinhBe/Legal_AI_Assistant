"""Embedding văn bản lớn trên Kaggle GPU thay vì CPU máy nhà (Minh 20/11/2026).

    # nạp văn bản không tạo embedding trong máy:
    #   docker compose exec -e EMBED_DEFER=true api python -m scripts.fetch_corpus_ext ...
    python -X utf8 tools/kaggle_embed.py --push      # hàng đợi -> dataset + kernel (minhart, GPU)
    python -X utf8 tools/kaggle_embed.py --collect   # tải vector về, ghi vào DB (không nạp model)

Chỉ văn bản luật công khai (data/embed_queue/*.jsonl: node_id + chuỗi cần nhúng). Không có key,
không có dữ liệu cá nhân. Model và cách chuẩn hoá giống app/rag/embeddings.py
(AITeamVN/Vietnamese_Embedding_v2, normalize_embeddings=True).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "data" / "embed_queue"
OUT = ROOT / "data" / "embed_out"
STAGE = ROOT / "data" / "finetune" / "kaggle_stage" / "minhart"
DS, KR = STAGE / "ds_embed", STAGE / "kernel_embed"
DATASET, KERNEL = "minhart/lawvn-embed-queue", "minhart/lawvn-embed"
MODEL = "AITeamVN/Vietnamese_Embedding_v2"

NOTEBOOK_CODE = f'''
import glob, json, numpy as np, torch
from sentence_transformers import SentenceTransformer
q = sorted(glob.glob("/kaggle/input/**/queue.jsonl", recursive=True))[0]
rows = [json.loads(x) for x in open(q, encoding="utf-8") if x.strip()]
print(len(rows), "chuỗi", torch.cuda.is_available())
m = SentenceTransformer("{MODEL}", device="cuda" if torch.cuda.is_available() else "cpu")
m.half()
order = sorted(range(len(rows)), key=lambda i: len(rows[i]["ctx"]))  # nhóm theo độ dài: ít đệm
vecs = m.encode([rows[i]["ctx"] for i in order], batch_size=64, normalize_embeddings=True,
                show_progress_bar=True, convert_to_numpy=True).astype("float32")
out = np.zeros_like(vecs)
out[order] = vecs
np.save("/kaggle/working/vectors.npy", out)
json.dump([r["node_id"] for r in rows], open("/kaggle/working/ids.json", "w"))
print("xong", out.shape)
'''


def kaggle(*args: str, timeout: int = 1800) -> str:
    exe = Path.home() / "AppData/Roaming/Python/Python312/Scripts/kaggle.exe"
    cmd = [str(exe)] if exe.exists() else [sys.executable, "-m", "kaggle"]
    p = subprocess.run(cmd + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env={**os.environ, "PYTHONUTF8": "1"})
    return (p.stdout or "") + (p.stderr or "")


def push() -> None:
    files = sorted(QUEUE.glob("*.jsonl"))
    if not files:
        print("hàng đợi trống")
        return
    DS.mkdir(parents=True, exist_ok=True)
    n = 0
    with (DS / "queue.jsonl").open("w", encoding="utf-8") as out:
        for f in files:
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.write(line + "\n")
                    n += 1
    print(n, "chuỗi từ", len(files), "tệp")
    meta = DS / "dataset-metadata.json"
    first = not meta.exists()
    meta.write_text(json.dumps({"title": "lawvn-embed-queue", "id": DATASET,
                                "licenses": [{"name": "other"}]}), encoding="utf-8")
    if first:
        print(kaggle("datasets", "create", "-p", str(DS.resolve())).strip()[-300:])
    else:
        print(kaggle("datasets", "version", "-p", str(DS.resolve()), "-m", f"{n} chuỗi").strip()[-300:])
    for _ in range(30):  # đợi phiên bản dataset sẵn sàng
        if "ready" in kaggle("datasets", "status", DATASET, timeout=120):
            break
        time.sleep(20)
    KR.mkdir(parents=True, exist_ok=True)
    nb = {"metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5,
          "cells": [{"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                     "source": NOTEBOOK_CODE.strip()}]}
    (KR / "embed.ipynb").write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
    (KR / "kernel-metadata.json").write_text(json.dumps({
        "id": KERNEL, "title": "lawvn-embed", "code_file": "embed.ipynb", "language": "python",
        "kernel_type": "notebook", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [DATASET], "competition_sources": [], "kernel_sources": [],
        "machine_shape": "NvidiaTeslaT4"}, indent=1), encoding="utf-8")
    print(kaggle("kernels", "push", "-p", str(KR.resolve())).strip()[-300:])


def collect() -> None:
    status = kaggle("kernels", "status", KERNEL, timeout=120)
    if "COMPLETE" not in status:
        print("chưa xong:", status.strip()[-120:])
        return
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    print(kaggle("kernels", "output", KERNEL, "-p", str(OUT.resolve()),
                 "--file-pattern", r"^(vectors\.npy|ids\.json)$", "-o", "-q").strip()[-300:])
    r = subprocess.run(["docker", "compose", "exec", "-T", "api", "python", "-m",
                        "scripts.apply_embeddings", "--dir", "data/embed_out"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    print((r.stdout + r.stderr).strip()[-500:])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--collect", action="store_true")
    a = ap.parse_args()
    if a.push:
        push()
    if a.collect:
        collect()


if __name__ == "__main__":
    main()
