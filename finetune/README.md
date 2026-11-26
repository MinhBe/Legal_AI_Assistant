# Fine-tune Qwen2.5-7B cho Legal Agentic (KG1)

Mục tiêu: một mô hình 7B "nói như luật sư lao động Việt Nam" để câu trả lời tự nhiên hơn,
**không** thay RAG + Verifier — trích dẫn vẫn do code kiểm. Dữ liệu huấn luyện chỉ lấy từ
nguồn công khai (điều luật đã nạp, danh mục án lệ), không có tệp tải lên hay câu trả lời
của khách.

## 1. Dựng dữ liệu (trong container api)

```bash
docker compose exec -T api python -m scripts.ft_build --scope pilot --dry-run --out data/finetune/pilot
docker compose exec -T api python -m scripts.ft_build --scope pilot --pairs 3 --max-calls 60 --out data/finetune/pilot
```

`--scope pilot` = 20 điều/khoản ngẫu nhiên + 5 án lệ (mục tiêu ~50 cặp). `--dry-run` chỉ in số
lời gọi Dahl và token ước lượng, không gọi mô hình, không ghi tệp. Kết quả nằm trong
`data/finetune/<tên>/` (đã `.gitignore`): `train.jsonl`, `val.jsonl` (95/5), `manifest.json`
(nguồn, số cặp, số lý do loại, số lời gọi Dahl, git commit).

Lọc bằng code, không bằng mô hình: trích dẫn phải có thật trong kho và đúng mốc hiệu lực,
câu trả lời phải có dấu tiếng Việt, đúng độ dài, không gần trùng cặp đã giữ; câu hỏi gần trùng
câu hỏi vàng (cosine ≥ 0,85) bị bỏ để bộ đo còn giá trị.

Án lệ chưa có toàn văn đã duyệt thì **không** sinh cặp nào (không để mô hình bịa nội dung án lệ);
chúng vẫn được đếm trong `manifest.json`.

## 2. Huấn luyện trên Kaggle

1. Upload `train.jsonl` + `val.jsonl` + `train.py` + `export_gguf.py` thành một Kaggle Dataset
   (ví dụ `lawvn-ft`).
2. Notebook mới: **GPU T4 ×2**, **Internet on**, rồi mở `finetune/kaggle_qlora.ipynb` (hoặc
   upload tệp đó) và Run All. Chỉ cần sửa khối CONFIG ở đầu `train.py` (tên mô hình, đường dẫn
   dữ liệu, số epoch/bước).
3. Checkpoint mỗi 200 bước vào `/kaggle/working/ckpt`, giữ 2 bản mới nhất. Phiên 12 h tự dừng
   sạch ở 11 h 15 phút sau khi lưu.
4. Hết phiên: Save Version → mở lại notebook, thêm dòng `%run ... --resume` để chạy tiếp
   checkpoint mới nhất trong `/kaggle/working/ckpt` (cần giữ thư mục này qua Save Version).

Cấu hình: Qwen2.5-7B-Instruct 4-bit, LoRA r=16/alpha=16/dropout 0 trên toàn bộ lớp linear,
`max_length` 2048, batch 2 × grad-accum 4, lr 2e-4, 2 epoch, fp16 (T4 không có bf16),
gradient checkpointing của Unsloth.

## 3. Xuất GGUF cho Ollama

```python
%run /kaggle/input/lawvn-ft/export_gguf.py --adapter /kaggle/working/lora
```

Gộp LoRA → 16-bit → GGUF Q4_K_M, ghi `Modelfile` với `PARAMETER num_ctx 8192`, in ra:

```bash
ollama create lawvn-qwen7b-ft -f /đường/dẫn/gguf/Modelfile
```

## 4. Đo trước/sau (trong container api, cần Ollama có cả hai mô hình)

```bash
docker compose exec -T api python -m scripts.ft_eval --model qwen2.5:7b --model lawvn-qwen7b-ft --limit 20
```

Chạy đúng pipeline `answer_with_citations`, chỉ dùng mô hình trong máy, báo cáo tỉ lệ trích dẫn
đúng, số trích dẫn sai phiên bản, tỉ lệ JSON hợp lệ, số vấn đề Verifier, độ trễ trung bình; ghi
`data/finetune/eval-<ngày>.json`. **Cổng**: mô hình fine-tune chỉ được thay mô hình hiện tại khi
tỉ lệ trích dẫn đúng không thấp hơn và số trích dẫn sai phiên bản không cao hơn.

## 5. Lưu ý

- Nội dung luật trong dữ liệu sinh ra là **chưa được luật sư duyệt**; cần đọc mẫu trước khi dùng
  cho bản demo, và giữ `[cần đối chiếu]` cho chỗ chưa kiểm.
- Notebook tự cài gói trên Kaggle; ảnh `api` không thêm gói nào.
- Không đưa dữ liệu mức A/B vào dataset. Chỉ `legal_document` không phải `upload`, án lệ công khai
  và `case_problem` trạng thái `da_duyet`.
