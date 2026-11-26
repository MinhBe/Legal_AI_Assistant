# Codespaces cho LawVN (máy yếu vẫn code được)

Codespace này chỉ để **code hằng ngày**: sửa backend/frontend, chạy test, chạy Pi.
Phần nặng không chạy ở đây:

| Việc | Chạy ở đâu |
|---|---|
| Train, eval, che PII hàng loạt | Kaggle |
| Deploy | Vercel (tự build khi merge vào main) |
| Dữ liệu (corpus, pgvector) | Neon |
| LLM của app | Dahl API (không Ollama, không model 7B) |
| Agent code (lead / review / dev) | Pi trong Codespace, Codex qua đăng nhập ChatGPT |

## 1. Mở Codespace

1. Vào repo trên GitHub, bấm **Code → Codespaces → ⋯ → New with options**.
2. Branch `main`, **Machine type: 2-core** (8 GB RAM). Bấm **Create codespace**.
3. Lần đầu mất khoảng 5–8 phút (cài thư viện Python, Next.js, Pi). Các lần sau mở lại chỉ vài giây.

## 2. Secrets (đặt một lần, không bao giờ ghi key vào repo)

GitHub → **Settings → Codespaces → Secrets → New secret**, chọn repo này ở "Repository access".

| Tên secret | Bắt buộc | Giá trị |
|---|---|---|
| `DATABASE_URL` | có | Chuỗi kết nối Neon. Nên tạo một **nhánh dev** trên Neon để code không ghi vào dữ liệu demo. |
| `DAHL_TOKENS` | có | Các key Dahl, mỗi dòng một key (dán nguyên nội dung `dahl.keys` cũng được). App và Pi cùng dùng. |
| `OPENROUTER_KEYS` | cho Pi | Key OpenRouter (dev phụ), mỗi dòng một key. |
| `SCALEROUTER_KEYS` | tuỳ | Key ScaleRouter. Có thể bị chặn từ cloud; bị chặn thì Pi tự chuyển model khác. Đây là key mượn, thu hồi sau ~1 tuần. |
| `EMBEDDER` | tuỳ | Để trống = `hashing` (nhẹ). Đặt `vie-v2` khi cần tìm kiếm vector thật trên Neon (tải model ~2 GB lần đầu, dùng ~3 GB RAM). |

Không đặt ở đây: key DeepSeek, key Gemini, đăng nhập Claude.
Đổi secret xong thì **Restart codespace** để key mới có hiệu lực (`write-keys.sh` chạy mỗi lần khởi động).

## 3. Chạy app

```bash
bash .devcontainer/dev.sh        # API cổng 8000 + web cổng 3000
cd backend && pytest -q          # test backend
```

Mở cổng **3000** ở tab Ports. Web gọi API qua `/api/*` cùng địa chỉ, nên không cần mở cổng 8000 công khai.
Mọi cổng để **Private**.

Dữ liệu mức A/B (thông tin cá nhân) theo quy tắc chỉ được chạy bằng model trong máy. Codespace không có Ollama,
nên câu hỏi mức A/B sẽ báo "mô hình trong máy chưa sẵn sàng". Đó là đúng thiết kế, không phải lỗi.

## 4. Pi trong Codespace

Pi cài ở `/workspaces/.pi-dev` (ngoài repo, giữ lại cả khi Rebuild container). Cấu hình lấy từ `.devcontainer/pi/`
(bản Linux của `Documents\pi-dev`: roles.json, models.json, extension pi-rr / free-auto / sr-models / tps,
guard quyền, skill Addy @301b02b).

Đăng nhập 6 tài khoản ChatGPT một lần:

```bash
pi-role lead          # mở Pi
/login                # chọn "Sign in with an account" → OpenAI (business1)
                      # mở link trong cửa sổ ẩn danh, đăng nhập đúng tài khoản, nhập mã
```

Lặp lại `/login` cho business2…business5 và personal. Lead dùng business1, Review business2, Dev business3
(đổi bằng biến `PI_LEAD_ACCOUNT`, `PI_REVIEW_ACCOUNT`, `PI_DEV_ACCOUNT`). Hết lượt Codex thì Pi rơi xuống
model miễn phí (OpenRouter, ScaleRouter, Dahl).

```bash
pi-role lead      # lên kế hoạch
pi-role dev       # viết code
pi-role review    # review (không có quyền edit/write)
```

Đăng nhập nằm trong `/workspaces/.pi-dev/agent/auth.json` của riêng Codespace này. Xoá Codespace là mất, phải đăng nhập lại.
Không đưa đăng nhập Claude vào Pi.

Sửa cấu hình Pi: sửa trong `.devcontainer/pi/` rồi chạy lại `bash .devcontainer/pi/setup-pi.sh`.

## 5. Giữ chi phí 0 đồng

- GitHub → **Settings → Billing and licensing → Budgets and alerts**: budget cho Codespaces = **$0**, bật
  "Stop usage when budget limit is reached". Hết hạn mức miễn phí thì Codespace dừng, không tính tiền.
- Hạn mức miễn phí tài khoản cá nhân: 120 giờ-lõi/tháng (máy 2-core = 60 giờ chạy) và 15 GB lưu trữ.
- **Settings → Codespaces**: Default idle timeout = **15 phút**, Default retention period = **7 ngày**.
- Không bật Prebuilds (tốn lưu trữ). Xong việc thì **Stop codespace**; xoá các codespace cũ không dùng.
- Muốn trả phí sau: chỉ cần nâng budget, không phải đổi gì trong repo.

## 6. Tắt Ollama trên máy nhà (app dùng Dahl)

Trên máy Minh (`Documents\RAG\RAG`):

1. Trong `.env` đặt (hoặc kiểm tra đã có):
   ```
   CLOUD_FIRST_FOR_C=true
   NO_LOCAL_FOR_C=true
   CLOUD_SPREAD_MODELS=true
   ```
   Key Dahl đã có trong `keys\dahl.keys`.
2. Tắt Ollama: chuột phải biểu tượng Ollama ở khay hệ thống → **Quit Ollama**. Không cho tự chạy:
   Task Manager → Startup apps → Ollama → **Disable**.
3. Khởi động lại API: `docker compose up -d --force-recreate api`.

Kết quả: mọi câu hỏi mức C đi Dahl. Câu hỏi mức A/B bị từ chối có thông báo (quy tắc riêng tư không đổi).
Muốn bật lại: mở Ollama và khởi động lại API.
