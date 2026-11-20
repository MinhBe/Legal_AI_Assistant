"""Sinh dữ liệu train bằng model mở trên Kaggle GPU (minhart, 1 phiên; phiên kia để train v1).

    docker compose exec api python -m scripts.ft_kaggle_gen export --n 30
    python -X utf8 tools/kaggle_gen.py --push [--model Qwen/Qwen2.5-14B-Instruct-AWQ]
    python -X utf8 tools/kaggle_gen.py --collect
    docker compose exec api python -m scripts.ft_kaggle_gen import --compare

Đầu vào chỉ là prompt dựng từ văn bản luật công khai (data/finetune/kaggle_gen/prompts.jsonl).
Không key, không ghi âm, không câu hỏi vàng. Notebook thử vLLM (T4 x2, tensor parallel);
không cài được thì dùng transformers + 4-bit.
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
SRC = ROOT / "data" / "finetune" / "kaggle_gen"
STAGE = ROOT / "data" / "finetune" / "kaggle_stage" / "minhart"
DS, KR = STAGE / "ds_gen", STAGE / "kernel_gen"
DATASET, KERNEL = "minhart/lawvn-gen-prompts", "minhart/lawvn-gen"

CODE = r'''
import glob, json, os, subprocess, sys, time
MODEL = "__MODEL__"
src = sorted(glob.glob("/kaggle/input/**/prompts.jsonl", recursive=True))[0]
rows = [json.loads(x) for x in open(src, encoding="utf-8") if x.strip()]
print(len(rows), "prompt")
t0 = time.time()
texts, engine = None, ""
try:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "vllm"], check=True, timeout=1500)
    from vllm import LLM, SamplingParams
    llm = LLM(MODEL, tensor_parallel_size=2, dtype="half", max_model_len=8192,
              gpu_memory_utilization=0.90, enforce_eager=True)
    sp = SamplingParams(temperature=0.7, max_tokens=3000)
    outs = llm.chat([r["messages"] for r in rows], sp)
    texts, engine = [o.outputs[0].text for o in outs], "vllm"
except Exception as exc:
    print("vLLM không chạy được:", repr(exc)[:300])
if texts is None:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    name = MODEL.replace("-AWQ", "")
    tok = AutoTokenizer.from_pretrained(name)
    tok.padding_side = "left"
    m = AutoModelForCausalLM.from_pretrained(name, device_map="auto",
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16))
    texts, engine = [], "hf-4bit"
    for i in range(0, len(rows), 8):
        prompts = [tok.apply_chat_template(r["messages"], add_generation_prompt=True, tokenize=False) for r in rows[i:i+8]]
        enc = tok(prompts, return_tensors="pt", padding=True).to(m.device)
        with torch.no_grad():
            out = m.generate(**enc, max_new_tokens=3000, do_sample=True, temperature=0.7)
        texts += [tok.decode(o[enc["input_ids"].shape[1]:], skip_special_tokens=True) for o in out]
        print(i + 8, "/", len(rows), round(time.time() - t0), "s", flush=True)
os.makedirs("/kaggle/working/out", exist_ok=True)
with open("/kaggle/working/out/outputs.jsonl", "w", encoding="utf-8") as f:
    for r, t in zip(rows, texts):
        f.write(json.dumps({"source": r["source"], "text": t, "model": MODEL, "engine": engine}, ensure_ascii=False) + "\n")
print("xong", engine, len(texts), round(time.time() - t0), "s")
'''


def kaggle(*args: str, timeout: int = 1800) -> str:
    exe = Path.home() / "AppData/Roaming/Python/Python312/Scripts/kaggle.exe"
    cmd = [str(exe)] if exe.exists() else [sys.executable, "-m", "kaggle"]
    p = subprocess.run(cmd + list(args), capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=timeout, env={**os.environ, "PYTHONUTF8": "1"})
    return (p.stdout or "") + (p.stderr or "")


def push(model: str) -> None:
    DS.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC / "prompts.jsonl", DS / "prompts.jsonl")
    meta = DS / "dataset-metadata.json"
    first = not meta.exists()
    meta.write_text(json.dumps({"title": "lawvn-gen-prompts", "id": DATASET,
                                "licenses": [{"name": "other"}]}), encoding="utf-8")
    print(kaggle("datasets", "create" if first else "version", "-p", str(DS.resolve()),
                 *([] if first else ["-m", "prompts"])).strip()[-200:])
    for _ in range(30):
        if "ready" in kaggle("datasets", "status", DATASET, timeout=120):
            break
        time.sleep(20)
    KR.mkdir(parents=True, exist_ok=True)
    nb = {"metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                       "language_info": {"name": "python"}},
          "nbformat": 4, "nbformat_minor": 5,
          "cells": [{"cell_type": "code", "metadata": {}, "execution_count": None, "outputs": [],
                     "source": CODE.replace("__MODEL__", model).strip()}]}
    (KR / "gen.ipynb").write_text(json.dumps(nb, ensure_ascii=False), encoding="utf-8")
    (KR / "kernel-metadata.json").write_text(json.dumps({
        "id": KERNEL, "title": "lawvn-gen", "code_file": "gen.ipynb", "language": "python",
        "kernel_type": "notebook", "is_private": True, "enable_gpu": True, "enable_internet": True,
        "dataset_sources": [DATASET], "competition_sources": [], "kernel_sources": [],
        "machine_shape": "NvidiaTeslaT4"}, indent=1), encoding="utf-8")
    print(kaggle("kernels", "push", "-p", str(KR.resolve())).strip()[-200:])


def collect() -> None:
    s = kaggle("kernels", "status", KERNEL, timeout=120)
    if "COMPLETE" not in s:
        print("chưa xong:", s.strip()[-120:])
        return
    out = SRC / "out"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    print(kaggle("kernels", "output", KERNEL, "-p", str(out.resolve()),
                 "--file-pattern", r".*(outputs\.jsonl|\.log)$", "-o", "-q").strip()[-200:])
    for f in out.rglob("outputs.jsonl"):
        if f.parent != out:
            shutil.move(str(f), out / "outputs.jsonl")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--collect", action="store_true")
    ap.add_argument("--model", default="Qwen/Qwen2.5-14B-Instruct-AWQ")
    a = ap.parse_args()
    if a.push:
        push(a.model)
    if a.collect:
        collect()


if __name__ == "__main__":
    main()
