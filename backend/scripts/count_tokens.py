"""Đo token: (1) số token mỗi node theo tokenizer của model embedding, và số node bị cắt khi embed;
(2) tỉ lệ token tiếng Việt / tiếng Anh cho cùng 10 Điều BLLĐ 2019.

    docker compose exec api python -m scripts.count_tokens --phase all

Không có bản tiếng Anh chính thức trong data/raw (đã kiểm tra _metadata.parquet): theo kế hoạch
V3.5 mục 3, bản tiếng Anh do máy dịch bằng Dahl, và ghi rõ là máy dịch. Tỉ lệ đo ngôn ngữ, không
đo độ chính xác pháp lý.
"""

from __future__ import annotations

import argparse
import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from openai import OpenAI
from sqlalchemy import text

from app.config import get_settings
from app.db.base import SessionLocal
from app.rag.embeddings import _load_model

RESULTS_DIR = Path(__file__).resolve().parents[1] / "eval" / "results"
SAMPLE_ARTICLES = [25, 27, 35, 36, 41, 46, 98, 107, 113, 139]  # 10 Điều đã dùng trong gold set


def phase1_node_tokens() -> dict:
    m = _load_model()
    tok = m.tokenizer
    max_len = m.max_seq_length
    db = SessionLocal()
    try:
        rows = db.execute(text("SELECT level, text FROM legal_node")).all()
    finally:
        db.close()
    by_level: dict[str, list[int]] = {}
    for level, body in rows:
        n = len(tok(body, add_special_tokens=True)["input_ids"])
        by_level.setdefault(level, []).append(n)
    out = {"max_seq_length": max_len, "levels": {}}
    for level, ns in by_level.items():
        ns_sorted = sorted(ns)
        out["levels"][level] = {
            "n": len(ns),
            "p50": ns_sorted[len(ns_sorted) // 2],
            "p95": ns_sorted[int(0.95 * (len(ns_sorted) - 1))],
            "max": ns_sorted[-1],
            "over_max_seq": sum(1 for x in ns if x > max_len),
        }
    total_over = sum(v["over_max_seq"] for v in out["levels"].values())
    out["total_over_max_seq"] = total_over
    print(f"max_seq_length={max_len}; số node vượt giới hạn khi embed: {total_over}")
    for level, v in out["levels"].items():
        print(f"  {level:8} n={v['n']:5} p50={v['p50']:4} p95={v['p95']:4} max={v['max']:5} vượt={v['over_max_seq']}")
    return out


def _dahl_client() -> OpenAI:
    s = get_settings()
    return OpenAI(base_url=s.dahl_base_url, api_key=s.dahl_keys[0], max_retries=3, timeout=180)


def _prompt_tokens(client: OpenAI, model: str, content: str) -> int:
    r = client.chat.completions.create(model=model, messages=[{"role": "user", "content": content}],
                                       max_tokens=1, temperature=0)
    return r.usage.prompt_tokens


def _translate(client: OpenAI, model: str, vi: str) -> str:
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": "Dịch đúng nghĩa điều luật sau sang tiếng Anh. "
                                                "Chỉ trả về bản dịch, không giải thích."},
                  {"role": "user", "content": vi}],
        max_tokens=4000, temperature=0)
    return (r.choices[0].message.content or "").strip()


def phase2_vi_en(model: str = "zai-org/GLM-5.3-Flash") -> dict:
    db = SessionLocal()
    try:
        vi_texts = []
        for n in SAMPLE_ARTICLES:
            body = db.execute(text(
                "SELECT string_agg(text, ' ' ORDER BY seq) FROM legal_node "
                "WHERE doc_id='blld2019' AND (node_id = :a OR parent_id = :a)"),
                {"a": f"blld2019-d{n}"}).scalar()
            vi_texts.append((n, body or ""))
    finally:
        db.close()

    client = _dahl_client()
    overhead = _prompt_tokens(client, model, "x")

    try:
        import tiktoken
        enc = tiktoken.get_encoding("o200k_base")
    except Exception:  # noqa: BLE001 — tiktoken không cài được thì bỏ cột này
        enc = None

    rows = []
    for n, vi in vi_texts:
        if not vi:
            continue
        en = _translate(client, model, vi)
        vi_tok = _prompt_tokens(client, model, vi) - overhead
        en_tok = _prompt_tokens(client, model, en) - overhead
        row = {"article": n, "chars_vi": len(vi), "chars_en": len(en),
               "dahl_vi": vi_tok, "dahl_en": en_tok, "ratio_dahl": round(vi_tok / en_tok, 3) if en_tok else None}
        if enc is not None:
            row["tiktoken_vi"] = len(enc.encode(vi))
            row["tiktoken_en"] = len(enc.encode(en))
            row["ratio_tiktoken"] = round(row["tiktoken_vi"] / row["tiktoken_en"], 3)
        rows.append(row)
        print(f"  Điều {n}: VN={vi_tok} EN={en_tok} ratio={row['ratio_dahl']}", flush=True)

    ratios = [r["ratio_dahl"] for r in rows if r["ratio_dahl"]]
    summary = {
        "model": model, "overhead_tokens": overhead, "translation": "máy dịch (không có bản chính thức)",
        "rows": rows,
        "ratio_dahl_mean": round(statistics.fmean(ratios), 3) if ratios else None,
        "ratio_dahl_min": min(ratios) if ratios else None,
        "ratio_dahl_max": max(ratios) if ratios else None,
    }
    print(f"tỉ lệ token VN/EN (Dahl): trung bình={summary['ratio_dahl_mean']} "
          f"khoảng={summary['ratio_dahl_min']}–{summary['ratio_dahl_max']}")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["1", "2", "all"], default="all")
    args = ap.parse_args()
    out = {"ts": datetime.now(UTC).isoformat()}
    if args.phase in ("1", "all"):
        out["phase1_nodes"] = phase1_node_tokens()
    if args.phase in ("2", "all"):
        out["phase2_vi_en"] = phase2_vi_en()
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    path = RESULTS_DIR / f"{stamp}_count_tokens.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"Ghi: {path}")


if __name__ == "__main__":
    main()
