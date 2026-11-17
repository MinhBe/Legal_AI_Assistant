"""QLoRA Qwen2.5-7B-Instruct cho LawVN, chạy trên Kaggle (KG1).

Notebook `finetune/kaggle_qlora.ipynb` chỉ `%run` tệp này. Sửa cấu hình ở khối CONFIG
bên dưới là đủ. Unsloth/transformers/trl chỉ được import trong `main()`, nên tệp này
`py_compile` được ở máy không GPU.

    %run /kaggle/input/lawvn-ft/train.py            # chạy mới
    %run /kaggle/input/lawvn-ft/train.py --resume   # chạy tiếp checkpoint mới nhất
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

# ── CONFIG ────────────────────────────────────────────────────────────────────
MODEL_NAME = "unsloth/Qwen2.5-7B-Instruct"
DATA_DIR = Path("/kaggle/input/lawvn-ft")  # train.jsonl + val.jsonl trong dataset Kaggle
OUT_DIR = Path("/kaggle/working")
MAX_SEQ_LEN = 2048
EPOCHS = 2
MAX_STEPS = -1  # >0 thì dừng theo bước thay vì theo epoch
CKPT_EVERY = 200
KEEP_LAST = 2
TIME_GUARD_S = 11 * 3600 + 15 * 60  # phiên Kaggle 12 h: dừng sớm 45 phút để kịp lưu
# ──────────────────────────────────────────────────────────────────────────────


def load_rows(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def to_text(rows: list[dict], tokenizer) -> list[dict]:
    return [{"text": tokenizer.apply_chat_template(r["messages"], tokenize=False)} for r in rows]


def _checkpoints(ckpt_dir: Path) -> list[Path]:
    found = [p for p in ckpt_dir.glob("checkpoint-*") if p.name.split("-")[-1].isdigit()]
    return sorted(found, key=lambda p: int(p.name.split("-")[-1]))


def latest_checkpoint(ckpt_dir: Path = OUT_DIR / "ckpt") -> Path | None:
    found = _checkpoints(ckpt_dir)
    return found[-1] if found else None


def prune(ckpt_dir: Path = OUT_DIR / "ckpt", keep: int = KEEP_LAST) -> None:
    """Chỉ giữ `keep` checkpoint mới nhất (Kaggle chỉ cho 57 GB đĩa)."""
    for old in _checkpoints(ckpt_dir)[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def time_guard_class():
    """Callback dừng sạch khi sắp hết phiên — import transformers ở đây, không ở đầu tệp."""
    from transformers import TrainerCallback

    class TimeGuard(TrainerCallback):
        def __init__(self, limit_s: float = TIME_GUARD_S) -> None:
            self.t0 = time.monotonic()
            self.limit_s = limit_s
            self.tripped = False

        def on_step_end(self, args, state, control, **kwargs):
            if time.monotonic() - self.t0 > self.limit_s:
                self.tripped = True
                control.should_training_stop = True
                control.should_save = True

    return TimeGuard


def main() -> None:
    ap = argparse.ArgumentParser(description="QLoRA Qwen2.5-7B cho LawVN (Kaggle)")
    ap.add_argument("--data", default=str(DATA_DIR))
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--epochs", type=int, default=EPOCHS)
    ap.add_argument("--max-steps", type=int, default=MAX_STEPS)
    ap.add_argument("--resume", action="store_true", help="chạy tiếp checkpoint mới nhất")
    args = ap.parse_args()

    from datasets import Dataset
    from trl import SFTConfig, SFTTrainer
    from unsloth import FastLanguageModel

    data, out = Path(args.data), Path(args.out)
    ckpt_dir = out / "ckpt"

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=MODEL_NAME, max_seq_length=MAX_SEQ_LEN, dtype=None, load_in_4bit=True
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=16,
        lora_dropout=0,
        target_modules="all-linear",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    train = Dataset.from_list(to_text(load_rows(data / "train.jsonl"), tokenizer))
    val_path = data / "val.jsonl"
    val = Dataset.from_list(to_text(load_rows(val_path), tokenizer)) if val_path.exists() else None

    guard = time_guard_class()()
    cfg = SFTConfig(
        output_dir=str(ckpt_dir),
        per_device_train_batch_size=2,
        gradient_accumulation_steps=4,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=2e-4,
        lr_scheduler_type="linear",
        warmup_steps=5,
        fp16=True,  # T4 không có bf16
        bf16=False,
        logging_steps=10,
        save_steps=CKPT_EVERY,
        save_total_limit=KEEP_LAST,
        optim="adamw_8bit",
        weight_decay=0.01,
        seed=42,
        report_to="none",
        dataset_text_field="text",
        max_length=MAX_SEQ_LEN,  # trl cũ dùng max_seq_length
    )
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train,
        eval_dataset=val,
        args=cfg,
        callbacks=[guard],
    )

    resume = latest_checkpoint(ckpt_dir) if args.resume else None
    print(f"Bắt đầu (resume từ {resume})" if resume else "Bắt đầu từ đầu", flush=True)
    trainer.train(resume_from_checkpoint=str(resume) if resume else None)

    model.save_pretrained(str(out / "lora"))
    tokenizer.save_pretrained(str(out / "lora"))
    prune(ckpt_dir)
    print(f"Đã lưu LoRA vào {out / 'lora'} · time guard: {guard.tripped}", flush=True)


if __name__ == "__main__":
    main()
