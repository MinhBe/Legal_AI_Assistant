# Đổi mô hình AI

Ứng dụng có hai tuyến mô hình. Đổi mô hình chỉ cần sửa `.env` (và thư mục `keys/`) rồi tạo lại
container api, không sửa code.

| Mức dữ liệu | Tuyến | Biến cấu hình |
|---|---|---|
| A (tệp tải lên), B (có dữ liệu cá nhân) | Chỉ mô hình chạy trong máy (Ollama). Không bao giờ ra ngoài. | `OLLAMA_BASE_URL`, `LOCAL_MODEL`, `LOCAL_TIMEOUT` |
| C (câu hỏi thuần pháp lý) | Mô hình trong máy trước, lỗi thì sang mô hình đám mây (hoặc ngược lại với `CLOUD_FIRST_FOR_C=true`) | `CLOUD_LLM_*`, `CLOUD_FIRST_FOR_C` |

## Key của mô hình đám mây

- Đặt key vào thư mục `keys/` ở gốc repo, mỗi dòng `TÊN=key` hoặc chỉ `key`. Tệp bắt đầu bằng `.` bị bỏ qua.
- `docker-compose.yml` mount `./keys` vào `/keys` (chỉ đọc). `keys/` nằm trong `.gitignore` và `.dockerignore`.
- Có nhiều key thì mỗi lời gọi dùng key kế tiếp (xoay vòng). Key lỗi bị cho nghỉ rồi thử key sau:
  - 402 (hết hạn mức), 401, 403: cả key nghỉ 1 giờ.
  - 429, 5xx, hết giờ, lỗi mạng: chỉ cặp key + model đó nghỉ 90 giây.
  - Hết key dùng được thì chuyển sang model dự phòng.
- Log chỉ ghi số thứ tự key (`key #2`), không bao giờ ghi giá trị.
- Thư mục trống thì dùng biến môi trường có tên trong `CLOUD_LLM_API_KEY_ENV` (mặc định `Dahl_token_1`).

## Đổi mô hình đám mây (mức C)

Mọi nhà cung cấp có endpoint tương thích OpenAI đều dùng được (Dahl, DeepSeek, OpenRouter, vLLM...).

1. Thay key trong `keys/` (hoặc đặt biến ở `CLOUD_LLM_API_KEY_ENV`).
2. Sửa trong `.env`:
   - `CLOUD_LLM_BASE_URL`: địa chỉ endpoint, ví dụ `https://inference.dahl.global/v1`.
   - `CLOUD_LLM_MODEL`: model chính.
   - `CLOUD_LLM_FALLBACK_MODELS`: model dự phòng, cách nhau bằng dấu phẩy, thử theo thứ tự.
   - `CLOUD_LLM_REASONING_EFFORT`: `low` cho model có suy nghĩ; để trống nếu nhà cung cấp báo lỗi tham số này.
   - `CLOUD_FIRST_FOR_C=true` nếu muốn câu mức C dùng mô hình đám mây trước (mạnh hơn mô hình 7B trong máy).
3. Tạo lại container: `docker compose up -d --force-recreate api`.
4. Kiểm tra: `curl http://localhost:8000/health` phải có `"cloud": true`.

Câu trả lời của model đám mây bị loại (rồi chuyển sang model dự phòng) khi rỗng hoặc có chữ Hán/kana/Hangul.

`DEEPSEEK_BASE_URL` / `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL` là tên cũ, chỉ được dùng khi không có
key nào trong `keys/` hay ở `CLOUD_LLM_API_KEY_ENV`.

## Model mặc định hiện tại (đo 2026-11-16)

Đo trên 3 câu golden (A01 nghỉ phép năm, A04 đơn phương chấm dứt, A08 lương làm đêm), dùng đúng
prompt trả lời của ứng dụng và xoay vòng qua 5 key Dahl:

| Model | Đúng điều luật | Lời gọi thành công | Thời gian khi thành công | Ghi chú |
|---|---|---|---|---|
| MiniMaxAI/MiniMax-M2.7 | 3/3 | 3/4 | 9 s, 11 s, 60 s | 1 lời gọi treo tới hết giờ |
| deepseek-ai/DeepSeek-V4-Flash-0731 | 2/2 | 2/9 | 10 s, 16 s | 5 lời gọi treo 120 s, 2 lần 429 |
| zai-org/GLM-5.3-Flash | – | 0/5 | – | 429 "at concurrency capacity" trên cả 5 key |

Vì vậy mặc định là MiniMax-M2.7, dự phòng DeepSeek-V4-Flash rồi GLM-5.3-Flash. Cả ba đều trả JSON
hợp lệ, không lộ `<think>`, không lặp chữ. Hết giờ để 45 s: lời gọi treo không bao giờ về.

## Đổi mô hình trong máy (mức A, B)

1. Tải model: `ollama pull <tên>`, ví dụ `ollama pull qwen2.5:14b`.
2. Đặt `LOCAL_MODEL=<tên>` trong `.env`, rồi tạo lại container api.
3. Model phải vừa VRAM. Máy hiện có 6 GB, nên giới hạn ngữ cảnh bằng biến `OLLAMA_CONTEXT_LENGTH=8192`
   (đặt cho Ollama, không phải trong `.env`). Ứng dụng giữ prompt dưới khoảng 6.000 token.
