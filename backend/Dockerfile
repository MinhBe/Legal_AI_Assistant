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

COPY . /app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
