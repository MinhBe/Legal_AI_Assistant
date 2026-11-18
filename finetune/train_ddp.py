"""QLoRA Qwen2.5-7B trên CẢ HAI T4 bằng TRL + accelerate (DDP) — phương án (b) để so với Unsloth 1 GPU.

    !accelerate launch --num_processes 2 --mixed_precision fp16 train_ddp.py \
        --data /kaggle/input/lawvn-ft --max-steps 50 --out /kaggle/working/ddp

Cùng siêu tham số với train.py (r=16, lr 2e-4, batch hiệu dụng 8): mỗi GPU batch 2 × tích luỹ 2
× 2 GPU = 8. Mô hình 4-bit đã lượng tử sẵn (unsloth/Qwen2.5-7B-Instruct-bnb-4bit, ~5 GB) nạp vào
từng GPU. Packing + tiền token hoá (dataset_num_proc=4) + DataLoader 4 luồng, pin_memory để CPU
không làm GPU chờ. Ghi metrics.json (thời gian/bước, token/giây) để chọn phương án nhanh hơn.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

MODEL_NAME = "unsloth/Qwen2.5-7B-Instruct-bnb-4bit"
MAX_SEQ_LEN = 2048
CKPT_EVERY = 200


def load_rows(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="/kaggle/input/lawvn-ft")
    ap.add_argument("--out", default="/kaggle/working/ddp")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    local_rank = int(os.environ.get("LOCAL_RANK", 0))
    out = Path(args.out)
    tok = AutoTokenizer.from_pretrained(MODEL_NAME)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16),
        device_map={"": local_rank}, torch_dtype=torch.float16,
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=16, lora_alpha=16, lora_dropout=0.0,
                                             target_modules="all-linear", task_type="CAUSAL_LM"))
    # model 4-bit lượng tử sẵn ghi dtype bfloat16 nên LoRA tạo ra là bf16; T4 chạy fp16 với
    # GradScaler, mà GradScaler không unscale được bf16 (lỗi smoke v2) -> tham số học để fp32
    for param in model.parameters():
        if param.requires_grad:
            param.data = param.data.float()

    def texts(name: str):
        p = Path(args.data) / name
        if not p.exists():
            return None
        return Dataset.from_list([{"text": tok.apply_chat_template(r["messages"], tokenize=False)}
                                  for r in load_rows(p)])

    cfg = SFTConfig(
        output_dir=str(out / "ckpt"),
        per_device_train_batch_size=2,
        gradient_accumulation_steps=2,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=2e-4,
        lr_scheduler_type="linear",
        warmup_steps=5,
        fp16=True,
        logging_steps=10,
        save_steps=CKPT_EVERY,
        save_total_limit=2,
        optim="paged_adamw_8bit",
        weight_decay=0.01,
        seed=42,
        report_to="none",
        dataset_text_field="text",
        max_length=MAX_SEQ_LEN,
        packing=True,
        dataset_num_proc=4,
        dataloader_num_workers=4,
        dataloader_pin_memory=True,
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        ddp_find_unused_parameters=False,
    )
    trainer = SFTTrainer(
        model=model, processing_class=tok, train_dataset=texts("train.jsonl"),
        eval_dataset=texts("val.jsonl"), args=cfg,
    )
    t0 = time.time()
    res = trainer.train(resume_from_checkpoint=args.resume or None)
    took = time.time() - t0
    if trainer.is_world_process_zero():
        steps = max(1, res.global_step)
        # packing: mỗi mẫu đủ MAX_SEQ_LEN token; batch toàn cục = 2 × 2 × số GPU
        world = int(os.environ.get("WORLD_SIZE", 1))
        tokens = steps * 2 * 2 * world * MAX_SEQ_LEN
        metrics = {"mode": f"ddp_{world}gpu", "steps": steps, "seconds": round(took, 1),
                   "s_per_step": round(took / steps, 2), "tokens_per_s": round(tokens / took),
                   "train_loss": res.training_loss}
        out.mkdir(parents=True, exist_ok=True)
        (out / "metrics.json").write_text(json.dumps(metrics, indent=1))
        trainer.model.save_pretrained(str(out / "lora"))
        tok.save_pretrained(str(out / "lora"))
        print(json.dumps(metrics), flush=True)


if __name__ == "__main__":
    main()
