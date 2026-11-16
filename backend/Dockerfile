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

COPY . /app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
