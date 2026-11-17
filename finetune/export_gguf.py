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
    args = ap.parse_args()

    from peft import PeftModel
    from unsloth import FastLanguageModel

    out = Path(args.out)
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME, max_seq_length=NUM_CTX, dtype=None, load_in_4bit=True
    )
    model = PeftModel.from_pretrained(model, args.adapter)

    model.save_pretrained_merged(str(out / "merged-16bit"), tokenizer, save_method="merged_16bit")
    model.save_pretrained_gguf(str(out / "gguf"), tokenizer, quantization_method="q4_k_m")

    gguf = next(iter((out / "gguf").glob("*.gguf")), None)
    if gguf is None:
        raise SystemExit(f"không thấy tệp .gguf trong {out / 'gguf'}")
    modelfile = write_modelfile(gguf)
    print(f"ollama create {OLLAMA_NAME} -f {modelfile}", flush=True)


if __name__ == "__main__":
    main()
