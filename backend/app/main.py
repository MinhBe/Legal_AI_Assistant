"""Điểm vào API — Trợ lý pháp luật lao động."""

from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import text

from app.api.routes import router
from app.auth import accounts
from app.db.base import Base, SessionLocal, engine
from app.demo_limits import DemoRateLimitMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # pgvector đã bật ở db/init; tạo bảng nếu chưa có.
    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.create_all(bind=engine)
    logger.info("DB sẵn sàng, bảng đã tạo.")
    # Tài khoản demo (AUTH1): tạo còn thiếu, đổi vai trò nếu roles.py đã đổi.
    db = SessionLocal()
    try:
        accounts.seed(db)
    except Exception as exc:  # noqa: BLE001 — không seed được thì API vẫn chạy, chỉ là chưa đăng nhập được
        logger.warning("Không tạo được tài khoản demo: {}", exc)
    finally:
        db.close()
    # Model embedding nạp lười mất ~12 giây, dồn hết vào câu hỏi đầu tiên sau mỗi
    # lần khởi động; nạp sẵn ở luồng nền để API vẫn lên ngay.
    threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()
    yield


def _warm_up() -> None:
    from app.rag.embeddings import embed_one

    t0 = time.monotonic()
    try:
        embed_one("khởi động")
        logger.info("Model embedding sẵn sàng sau {:.1f}s.", time.monotonic() - t0)
    except Exception as exc:  # noqa: BLE001 — không nạp được thì câu hỏi đầu tự nạp
        logger.warning("Nạp sẵn model embedding lỗi: {}", exc)


app = FastAPI(title="Trợ lý pháp luật lao động", version="0.1.0", lifespan=lifespan)

# Rate limiting cho demo công khai (bật khi DEMO_MODE=true)
app.add_middleware(DemoRateLimitMiddleware)

# CORS — cho phép cả localhost (dev) và domain Vercel (demo)
_extra_origins = [o.strip() for o in os.getenv("EXTRA_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        # chế độ ôn phỏng vấn: cùng frontend, mở ở cổng 3001
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        *_extra_origins,
    ],
    allow_methods=["*"],
    allow_headers=["Authorization", "X-Client-Id", "Content-Type", "*"],
)

app.include_router(router)
