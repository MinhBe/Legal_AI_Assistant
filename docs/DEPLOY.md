# Hướng dẫn Deploy Demo (HF Spaces + Neon + Vercel)

Stack miễn phí, phù hợp demo cho nhà tuyển dụng.

---

## 1. PostgreSQL — Neon (miễn phí)

1. Đăng ký tại https://neon.tech → tạo project **lawvn**.
2. Trong tab **Connection Details**, chọn **psycopg** → sao chép chuỗi kết nối:
   ```
   postgresql://lawvn:<pass>@ep-xxx.neon.tech/lawvn?sslmode=require
   ```
3. Lưu lại — dùng ở bước HF Spaces.

---

## 2. API + Embedding — Hugging Face Spaces

### 2.1 Tạo Space

1. https://huggingface.co/new-space → chọn **Docker**, đặt tên `lawvn-api`, **Public**.
2. Upload các file sau (hoặc dùng `git push` qua HF git):
   ```
   backend/                   ← toàn bộ thư mục backend/
   └── Dockerfile.space       ← đổi tên thành Dockerfile
   ```
   Cụ thể: tạo repo HF riêng chứa nội dung `backend/`, đặt `Dockerfile.space` là `Dockerfile`.

### 2.2 Biến môi trường (Repository → Settings → Variables and Secrets)

Demo chỉ dùng **Dahl** (20/11/2026): không đặt key Gemini hay DeepSeek ở bất kỳ dịch vụ nào.
Máy chủ demo không có Ollama, nên mọi lời gọi mức C đi đám mây.

| Tên biến | Giá trị | Loại |
|---|---|---|
| `DATABASE_URL` | chuỗi Neon bước 1 | **Secret** |
| `DAHL_TOKEN_1` … `DAHL_TOKEN_N` | mỗi biến một key Dahl (tối đa 30, router xoay vòng) | **Secret** |
| `NO_LOCAL_FOR_C` | `true` | Variable |
| `CLOUD_FIRST_FOR_C` | `true` | Variable |
| `CLOUD_SPREAD_MODELS` | `true` | Variable |
| `EMBEDDER` | `vie-v2` | Variable |
| `EMBED_DIM` | `1024` | Variable |
| `DEMO_MODE` | `true` | Variable |
| `EXTRA_CORS_ORIGINS` | URL Vercel (bước 3) | Variable |

Không đặt: `GEMINI_API_KEY*`, `DEEPSEEK_API_KEY`, `GEMINI_FOR_C`.

Lưu ý:
- Chép lời tức thì (micro) trên CPU của Space sẽ chậm; phần cứng cho chép lời đang chờ Minh chọn
  (GPU chỉ khi bấm micro, chỉ CPU, hay máy chủ GPU). Trang `/demo` vẫn chạy đủ vì có bản ghi sẵn.
- Dữ liệu khách thật (ghi âm, hồ sơ) không đưa lên bản demo công khai; xem Luật Bảo vệ dữ liệu
  cá nhân 91/2025/QH15 trước khi nhận dữ liệu thật [cần đối chiếu với luật sư].

### 2.3 Nạp dữ liệu lần đầu

Sau khi Space build xong, gọi endpoint ingest qua Swagger UI (`/docs`) hoặc curl:
```bash
HF_URL=https://minhbe-lawvn-api.hf.space
curl -X POST $HF_URL/api/admin/ingest   # nạp 3 văn bản luật từ HF datasets
curl -X POST $HF_URL/api/admin/diff     # tính quan hệ sửa đổi 2012→2019
curl -X POST $HF_URL/api/admin/precedents  # nạp 150 bản án
```
*(Cần thêm endpoint /admin/ingest nếu chưa có — xem notes bên dưới)*

---

## 3. Web — Vercel

1. https://vercel.com/new → **Import Git Repository** → chọn `MinhBe/RAG`.
2. **Root Directory**: `frontend`.
3. **Environment Variables**:
   ```
   NEXT_PUBLIC_API_BASE_URL = https://minhbe-lawvn-api.hf.space
   ```
4. Deploy → lấy URL (vd `lawvn.vercel.app`).
5. Quay lại HF Spaces, cập nhật `EXTRA_CORS_ORIGINS` = URL Vercel.

---

## 4. Kiểm tra sau khi deploy

```bash
# Health check
curl https://minhbe-lawvn-api.hf.space/health

# Thử chat
curl -N -X POST https://minhbe-lawvn-api.hf.space/api/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "Thời gian thử việc tối đa là bao lâu?", "thread_id": "test"}'
```

---

## Ghi chú

- **HF Spaces free tier** ngủ sau 48h không dùng; lần đầu sau ngủ mất ~60s để khởi động (tải model embedding).
- **Neon free tier** giới hạn 0.5 GB storage — đủ cho ~3.000 node + embedding 1024d.
- **Demo rate limit**: 20 câu/IP/ngày, 200 câu toàn hệ thống/ngày (cấu hình trong `DEMO_IP_LIMIT`, `DEMO_GLOBAL_LIMIT`).
