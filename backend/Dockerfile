FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

# Thư viện hệ thống tối thiểu cho psycopg và build nhẹ; tesseract (vie) cho OCR tài liệu tải lên.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
        tesseract-ocr tesseract-ocr-vie \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# AU1: chép lời ghi âm/video trong máy (Minh đồng ý cài 16/11/2026). Lớp riêng, đặt sau
# requirements để lớp torch đã cache không phải cài lại. Model whisper tải lúc dùng lần đầu
# vào /root/.cache (volume modelcache), không đóng vào image.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir "faster-whisper==1.1.1"
# Chép lời tức thì trên GPU (PhoWhisper nén, chỉ khi bấm micro): ctranslate2 cần cuBLAS/cuDNN
# của CUDA 12; image slim không có, nên lấy bánh xe pip của NVIDIA và chỉ đường dẫn thư viện.
RUN pip install --no-cache-dir nvidia-cublas-cu12 "nvidia-cudnn-cu12==9.*"
ENV LD_LIBRARY_PATH=/usr/local/lib/python3.12/site-packages/nvidia/cublas/lib:/usr/local/lib/python3.12/site-packages/nvidia/cudnn/lib

# LI2: trình duyệt headless để đọc trang JS (anle.toaan.gov.vn) và form tra cứu của
# vanban.chinhphu.vn (Minh đồng ý 16/11/2026). Chỉ Chromium, chạy CPU, không dùng GPU.
# `playwright install --with-deps` chưa hỗ trợ Debian của image này, nên dùng gói chromium của
# Debian và trỏ Playwright vào /usr/bin/chromium (PLAYWRIGHT_CHROMIUM_PATH).
RUN apt-get update && apt-get install -y --no-install-recommends chromium fonts-noto-core \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir "playwright==1.49.1"
ENV PLAYWRIGHT_CHROMIUM_PATH=/usr/bin/chromium

COPY . /app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
