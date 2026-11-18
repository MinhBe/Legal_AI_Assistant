"""So prompt v2 trên các đoạn bench: Dahl (từng model riêng) và mô hình trong máy.

  python -m scripts.spoken_v2_eval --round 1 --clips f0_900,f2_1800,f4_3600 \
      --models minimax,glm,deepseek,local

Nguồn mỗi đoạn là bản ĐÃ CHE ở data/raw/record/out/bench/:
A = PhoWhisper, B = medium, C = large-v3 (cùng ánh xạ che).
Kết quả: data/raw/record/out/v2/round<N>/<clip>.<model>.json (+ audit tự động).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.config import get_settings
from app.llm.context import cloud_first_scope, data_class_scope
from app.llm.router import get_router
from app.problems import spoken_v2

BENCH = Path("data/raw/record/out/bench")
OUT = Path("data/raw/record/out/v2")
MODELS = {
    "minimax": ("cloud", "MiniMaxAI/MiniMax-M2.7"),
    "glm": ("cloud", "zai-org/GLM-5.3-Flash"),
    "deepseek": ("cloud", "deepseek-ai/DeepSeek-V4-Flash-0731"),
    "local": ("local", None),
}
CORPUS = [
    "Bộ luật Lao động 2019 (45/2019/QH14)",
    "Bộ luật Lao động 2012 (10/2012/QH13, hết hiệu lực)",
    "Nghị định 145/2020/NĐ-CP",
]
SOURCES = {"A": "phowhisper-large-ct2", "B": "medium", "C": "large-v3"}


def _ts(seconds: str) -> str:
    s = int(float(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def load_sources(clip: str, names=("A", "B", "C")) -> dict[str, str]:
    out = {}
    for name in names:
        lines = (BENCH / f"{SOURCES[name]}.{clip}.masked.txt").read_text(encoding="utf-8")
        rows = []
        for line in lines.splitlines():
            if line.startswith("[") and "] " in line:
                t, text = line[1:].split("] ", 1)
                rows.append(f"[{_ts(t)}] {text}")
        out[name] = "\n".join(rows)
    return out


def caller(kind: str, model: str | None, stats: dict):
    router = get_router()
    settings = get_settings()

    def call(messages):
        t0 = time.monotonic()
        stats["calls"] += 1
        if kind == "cloud":
            # bản đã che, mức C, đúng một model (không rơi sang model khác để so cho công bằng)
            with data_class_scope("C"), cloud_first_scope(True):
                res = router._call_cloud(model, messages, 0.2, 6000, task="route")  # noqa: SLF001
        else:
            with data_class_scope("A"):
                res = router._call_local(settings.local_model, messages, 0.2, 3000,  # noqa: SLF001
                                         task="route")
        stats["seconds"] += time.monotonic() - t0
        stats["ids"].append(res.call_id)
        return res.text

    return call


def _tokens(ids: list) -> int:
    """Tổng token vào + ra của các lời gọi, đọc từ bản ghi đo lường."""
    want, total = set(ids), 0
    path = Path("data/metrics/llm_calls.jsonl")
    if not path.exists():
        return 0
    for line in path.read_text(encoding="utf-8").splitlines()[-5000:]:
        rec = json.loads(line)
        if rec.get("call_id") in want:
            total += (rec.get("input_tokens") or 0) + (rec.get("output_tokens") or 0)
    return total


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--round", type=int, default=1)
    p.add_argument("--clips", default="f0_900,f2_1800,f4_3600")
    p.add_argument("--models", default="minimax,glm,deepseek,local")
    args = p.parse_args()
    out = OUT / f"round{args.round}"
    out.mkdir(parents=True, exist_ok=True)
    for clip in args.clips.split(","):
        for name in args.models.split(","):
            path = out / f"{clip}.{name}.json"
            if path.exists():
                continue
            kind, model = MODELS[name]
            # 7B trong máy ngữ cảnh 8k: chỉ đưa hai nguồn
            sources = load_sources(clip, ("A", "B") if kind == "local" else ("A", "B", "C"))
            stats = {"calls": 0, "seconds": 0.0, "ids": []}
            result = spoken_v2.run(caller(kind, model, stats), sources, CORPUS)
            result["audit"] = spoken_v2.audit(result, "\n".join(sources.values()), CORPUS)
            result["stats"] = {**stats, "seconds": round(stats["seconds"]),
                               "tokens": _tokens(stats["ids"])}
            path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            print(clip, name, len(result["units"]), "units", result["errors"], result["audit"],
                  result["stats"], flush=True)


if __name__ == "__main__":
    main()
