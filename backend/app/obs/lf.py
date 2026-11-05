"""Gửi trace sang Langfuse (server v2). Mọi lỗi đều nuốt: Langfuse chỉ để xem."""
from __future__ import annotations

from loguru import logger

from app.config import get_settings

settings = get_settings()
_CLIENT = None
_BROKEN = False


def _client():
    global _CLIENT, _BROKEN
    if _BROKEN or not settings.langfuse_enabled:
        return None
    if _CLIENT is None:
        try:
            from langfuse import Langfuse

            _CLIENT = Langfuse(public_key=settings.langfuse_public_key,
                               secret_key=settings.langfuse_secret_key, host=settings.langfuse_host)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Không khởi tạo được Langfuse, tắt gửi trace: {}", exc)
            _BROKEN = True
            return None
    return _CLIENT


def send(row: dict, calls: list[dict]) -> None:
    lf = _client()
    if lf is None:
        return
    try:
        tr = lf.trace(id=row["request_id"], name=row["kind"], metadata=row,
                      input=row.get("question"), output=row.get("answer"))
        for c in calls:
            tr.generation(name=c["task"], model=c["model"],
                          usage={"input": c["input_tokens"] or 0, "output": c["output_tokens"] or 0},
                          metadata={k: c[k] for k in ("provider", "won", "latency_s", "error",
                                                       "estimated", "prompt_version", "attempts")})
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gửi Langfuse lỗi: {}", exc)


def flush() -> None:
    lf = _client()
    if lf is not None:
        try:
            lf.flush()
        except Exception:  # noqa: BLE001
            pass
