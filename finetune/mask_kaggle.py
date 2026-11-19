"""Che PII bản chép lời TRÊN KAGGLE (Minh 19/11/2026: chỉ tải bản đã che về máy).

Giống record_batch.mask_segments/mask_pass2 ở máy nhà: NER bằng Qwen2.5-7B-Instruct (cùng model
với Ollama qwen2.5:7b, ở đây 4-bit trên T4) theo cửa sổ 5 phút, rồi các lớp luật của
app/audio/spoken_pii.py che cả cửa sổ một lượt.

    python mask_kaggle.py --raw-dir <thư mục *.raw.json> --out /kaggle/working/masked

Đầu ra mỗi tệp: <stem>.masked.json (+ <stem>.pass2.masked.json). Ánh xạ che (chứa giá trị
gốc) KHÔNG được ghi ra output: chỉ in số lượng theo loại.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.audio.spoken_pii import add_ner, mask_lines  # noqa: E402

MODEL = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"


class HFRouter:
    """Đủ giao diện router.chat(messages, task=, temperature=) mà spoken_pii.ner_values dùng."""

    def __init__(self) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(MODEL)
        self.model = AutoModelForCausalLM.from_pretrained(MODEL, device_map="auto",
                                                          dtype=torch.float16)

    def chat(self, messages, task="route", temperature=0.0):
        ids = self.tok.apply_chat_template(messages, add_generation_prompt=True,
                                           return_tensors="pt").to(self.model.device)
        with self.torch.no_grad():
            out = self.model.generate(ids, max_new_tokens=512, do_sample=False)
        text = self.tok.decode(out[0][ids.shape[1]:], skip_special_tokens=True)
        return type("R", (), {"text": text})()


def mask_file(router, raw: dict, window_s: float = 300) -> tuple[list, dict]:
    segs = raw["segments"]
    mapping: dict[str, str] = {}
    windows: dict[int, list[str]] = {}
    for s in segs:
        windows.setdefault(int(s["start"] // window_s), []).append(s["text"])
    for texts in windows.values():
        add_ner(router, "\n".join(texts), mapping)
    masked = mask_lines([s["text"] for s in segs], mapping=mapping)
    return [{"start": s["start"], "end": s["end"], "text": t}
            for s, t in zip(segs, masked, strict=True)], mapping


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", required=True)
    ap.add_argument("--out", default="/kaggle/working/masked")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    router = HFRouter()
    for raw_path in sorted(Path(args.raw_dir).rglob("*.raw.json")):
        if raw_path.name.endswith(".pass2.raw.json"):
            continue
        stem = raw_path.name[: -len(".raw.json")]
        t0 = time.time()
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        segs, mapping = mask_file(router, raw)
        meta = {k: v for k, v in raw.items() if k != "segments"}
        (out / f"{stem}.masked.json").write_text(json.dumps(
            {**meta, "segments": segs, "masker": "mask_lines@kaggle"}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        p2 = raw_path.with_name(f"{stem}.pass2.raw.json")
        if p2.exists():
            win = json.loads(p2.read_text(encoding="utf-8"))
            masked = mask_lines([w["text"] for w in win["windows"]], mapping=mapping)
            (out / f"{stem}.pass2.masked.json").write_text(json.dumps(
                {"model": win["model"], "windows": [{**w, "text": t} for w, t in
                                                   zip(win["windows"], masked, strict=True)]},
                ensure_ascii=False, indent=1), encoding="utf-8")
        kinds = Counter(k.strip("[]").rsplit("_", 1)[0] for k in mapping)
        print(stem, len(segs), "đoạn,", dict(kinds), f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
