"""Gộp LoRA → 16-bit → GGUF Q4_K_M và ghi Modelfile cho Ollama (KG1).

Chạy trên Kaggle sau `train.py`:

    %run /kaggle/input/lawvn-ft/export_gguf.py --adapter /kaggle/working/lora

In ra lệnh `ollama create`; tải thư mục `gguf/` (gồm `Modelfile`) về máy rồi chạy lệnh đó.
"""

from __future__ import annotations

import argparse
from pathlib import Path

MODEL_NAME = "unsloth/Qwen2.5-7B-Instruct"
OLLAMA_NAME = "lawvn-qwen7b-ft"
NUM_CTX = 8192


def write_modelfile(gguf: Path, num_ctx: int = NUM_CTX) -> Path:
    modelfile = gguf.parent / "Modelfile"
    modelfile.write_text(
        f"FROM {gguf.resolve()}\nPARAMETER num_ctx {num_ctx}\n", encoding="utf-8"
    )
    return modelfile


def main() -> None:
    ap = argparse.ArgumentParser(description="Xuất GGUF Q4_K_M từ LoRA đã huấn luyện")
    ap.add_argument("--adapter", default="/kaggle/working/lora")
    ap.add_argument("--out", default="/kaggle/working")
    # /kaggle/working chỉ ~20 GB, mà Unsloth cần ~30 GB (gộp 16-bit + GGUF f16 + q4_k_m) cùng lúc
    # (lỗi export v3, 19/11/2026): làm ở /tmp (đĩa lớn hơn), chỉ chép tệp q4_k_m về --out
    ap.add_argument("--work", default="/tmp/lawvn-gguf")
    args = ap.parse_args()

    import shutil

    import torch
    from unsloth import FastLanguageModel

    out = Path(args.out)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    print("đĩa trống:", {p: round(shutil.disk_usage(p).free / 1e9, 1) for p in ("/tmp", str(out))},
          "GB", flush=True)
    # Nạp THẲNG thư mục adapter (Unsloth tự lấy model gốc trong adapter_config.json). Gắn adapter
    # bằng peft.PeftModel.from_pretrained thì Unsloth từ chối gộp (lỗi lượt train v0, 19/11/2026).
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.adapter, max_seq_length=NUM_CTX, dtype=torch.float16, load_in_4bit=True
    )
    # save_pretrained_gguf tự gộp LoRA; không lưu thêm bản 16-bit
    model.save_pretrained_gguf(str(work), tokenizer, quantization_method="q4_k_m")

    found = sorted(work.rglob("*.gguf"),
                   key=lambda p: ("q4_k_m" not in p.name.lower(), p.stat().st_size))
    if not found:
        raise SystemExit(f"không thấy tệp .gguf trong {work}")
    (out / "gguf").mkdir(parents=True, exist_ok=True)
    gguf = out / "gguf" / found[0].name
    shutil.copy2(found[0], gguf)  # chỉ tệp q4_k_m (~4–5 GB) về thư mục output của Kaggle
    print("GGUF:", gguf, round(gguf.stat().st_size / 1e9, 2), "GB", flush=True)
    modelfile = write_modelfile(gguf)
    print(f"ollama create {OLLAMA_NAME} -f {modelfile}", flush=True)


if __name__ == "__main__":
    main()
