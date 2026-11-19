"""Chấm base vs base+LoRA trên golden set, TRÊN KAGGLE (gói từ backend/scripts/build_eval_pack.py).

    CUDA_VISIBLE_DEVICES=0 python eval_kaggle.py --pack eval_pack.jsonl --name base --out r_base.json
    CUDA_VISIBLE_DEVICES=1 python eval_kaggle.py --pack eval_pack.jsonl --name v0 \
        --adapter <thư mục lora> --out r_v0.json

Chỉ số giống scripts/ft_eval.py:
- citation_hit_rate: câu có ít nhất một trích dẫn đúng điều kỳ vọng (cùng điều được tính);
- wrong_version: số trích dẫn tới bản hết hiệu lực tại ngày sự kiện;
- json_validity; no_citation: câu không có trích dẫn hợp lệ nào (từ chối / không căn cứ).
Trích dẫn chỉ tính khi nằm trong kết quả truy hồi, như pipeline.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date

BASE = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"


def parse_json(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        raw = raw[4:] if raw.lower().startswith("json") else raw
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("không có JSON")
    return json.loads(raw[start:end + 1])


def article_of(node_id: str) -> str:
    return "-".join(node_id.split("-")[:2])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--adapter", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-new", type=int, default=700)
    args = ap.parse_args()

    import torch
    from unsloth import FastLanguageModel

    model, tok = FastLanguageModel.from_pretrained(
        model_name=args.adapter or BASE, max_seq_length=8192, dtype=torch.float16,
        load_in_4bit=True)
    FastLanguageModel.for_inference(model)
    rows = [json.loads(x) for x in open(args.pack, encoding="utf-8") if x.strip()]
    hits = wrong = json_ok = no_cite = 0
    per, lat = [], []
    for r in rows:
        t0 = time.time()
        ids = tok.apply_chat_template(r["messages"], add_generation_prompt=True,
                                      return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(ids, max_new_tokens=args.max_new, do_sample=False)
        text = tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
        lat.append(time.time() - t0)
        cites: list[str] = []
        try:
            d = parse_json(text)
            json_ok += 1
            cites = [c for c in (d.get("citation_node_ids") or []) if c in set(r["hit_ids"])]
        except Exception:  # noqa: BLE001 — JSON hỏng: tính vào json_validity
            d = None
        want = set(r["expected"])
        arts = {article_of(n) for n in want}
        hit = any(c in want or article_of(c) in arts for c in cites)
        hits += int(hit)
        no_cite += int(not cites)
        eff = date.fromisoformat(r["effective"])
        for c in cites:
            vt = (r["versions"].get(c) or [None, None])[1]
            if vt and eff >= date.fromisoformat(vt):
                wrong += 1
        per.append({"id": r["id"], "hit": hit, "cites": cites, "json": d is not None,
                    "seconds": round(lat[-1], 1), "answer": text[:1500]})
        print(args.name, r["id"], "hit" if hit else "-", len(cites), f"{lat[-1]:.0f}s", flush=True)
    n = len(rows)
    res = {"model": args.name, "rows": n, "citation_hit_rate": round(hits / n, 3),
           "wrong_version": wrong, "json_validity": round(json_ok / n, 3),
           "no_citation": no_cite, "avg_latency_s": round(sum(lat) / n, 1), "per_row": per}
    json.dump(res, open(args.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print({k: v for k, v in res.items() if k != "per_row"}, flush=True)


if __name__ == "__main__":
    main()
