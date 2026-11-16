"""Vòng quét tin pháp luật mới (LI1).

Luồng nền (daemon) 15 phút kiểm tra một lần: nếu hôm nay chưa có lượt `schedule` nào sau
`intel_daily_hour` (giờ Asia/Ho_Chi_Minh) thì chạy một lượt. Khoá `_LOCK` bảo đảm không bao
giờ có hai lượt chạy cùng lúc; `run_scan` không bao giờ raise (chỉ ghi log và `intel_run.error`).
"""

from __future__ import annotations

import threading
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import IntelRun
from app.intel import analyze, sources, store
from app.intel.fetch import BLOCKED_STATUS, Fetcher

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
CHECK_EVERY_S = 15 * 60

_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None


def adapters() -> list[Any]:
    return [sources.ThuVienPhapLuat(), sources.LuatVietnam(), sources.AnLe()]


def is_running() -> bool:
    return _LOCK.locked()


def _scan_sources(db, settings) -> dict[str, dict[str, Any]]:
    """Đọc danh sách của từng nguồn, lưu tin mới. Trả `{source: {status, found, new}}`."""
    adapters_ = adapters()
    listing = tuple(url for adapter in adapters_ for url in adapter.listing_urls)
    fetcher = Fetcher(
        settings.intel_user_agent, settings.intel_delay_s, allowed_urls=listing
    )
    per_source: dict[str, dict[str, Any]] = {}
    for adapter in adapters_:
        status, found, new = "ok", 0, 0
        for url in adapter.listing_urls[: max(settings.intel_max_pages, 1)]:
            code, html = fetcher.get(url)
            if code in BLOCKED_STATUS:
                status = "blocked"  # bị chặn: không thử lại, luật sư tự lấy bản gốc
                continue
            if code != 200:
                status = "error"
                continue
            for data in adapter.parse(html, url):
                found += 1
                data["source"] = adapter.name
                data["labor_hint"] = sources.labor_hint(data)
                if store.add_item(db, data):
                    new += 1
        if status == "ok" and getattr(adapter, "last_status", "ok") != "ok":
            status = adapter.last_status  # bị chặn thì giữ `blocked`, không đổi thành needs_browser
        per_source[adapter.name] = {"status": status, "found": found, "new": new}
    return per_source


def run_scan(trigger: str = "schedule") -> int | None:
    """Một lượt quét. None = đang có lượt khác chạy. Không bao giờ raise."""
    if not _LOCK.acquire(blocking=False):
        logger.info("Đang có lượt quét khác — bỏ lượt {}", trigger)
        return None
    settings = get_settings()
    db = SessionLocal()
    run = None
    try:
        run = store.start_run(db, trigger)
        per_source = _scan_sources(db, settings)
        counts = analyze.analyse_pending(db)
        store.finish_run(db, run, per_source)
        logger.info(
            "Quét tin mới ({}): {} · phân tích {}", trigger,
            {name: (v["status"], v["new"]) for name, v in per_source.items()}, counts,
        )
        return run.id
    except Exception as exc:  # noqa: BLE001 — vòng nền không được chết vì một lỗi
        logger.warning("Lượt quét tin mới lỗi: {}", exc)
        try:
            if run is not None:
                store.finish_run(db, run, {}, f"{exc.__class__.__name__}: {exc}")
            else:
                db.rollback()
        except Exception:  # noqa: BLE001 — không ghi được thì thôi, log ở trên đã đủ
            pass
        return run.id if run is not None else None
    finally:
        db.close()
        _LOCK.release()


def due_now(now: datetime | None = None) -> bool:
    """Hôm nay đã có lượt quét theo lịch sau `intel_daily_hour` chưa?"""
    settings = get_settings()
    current = now or datetime.now(TZ)
    if current.hour < settings.intel_daily_hour:
        return False
    start = current.replace(hour=settings.intel_daily_hour, minute=0, second=0, microsecond=0)
    db = SessionLocal()
    try:
        last = db.scalar(
            select(IntelRun.started_at)
            .where(IntelRun.trigger == "schedule")
            .order_by(IntelRun.started_at.desc())
            .limit(1)
        )
    finally:
        db.close()
    if last is None:
        return True
    if last.tzinfo is None:  # cột timestamptz nhưng driver có thể trả naive
        last = last.replace(tzinfo=current.tzinfo)
    return last < start


def run_forever(interval: float = CHECK_EVERY_S) -> None:
    """Chờ `interval` giây rồi mới kiểm tra — không quét ngay khi API vừa khởi động."""
    while not _STOP.wait(interval):
        try:
            if get_settings().intel_enabled and due_now():
                run_scan("schedule")
        except Exception as exc:  # noqa: BLE001 — luồng nền phải sống tiếp
            logger.warning("Vòng kiểm tra tin mới lỗi: {}", exc)


def start(interval: float = CHECK_EVERY_S) -> None:
    global _THREAD
    if _THREAD is not None and _THREAD.is_alive():
        return
    _STOP.clear()
    _THREAD = threading.Thread(target=run_forever, name="intel-scheduler", args=(interval,), daemon=True)
    _THREAD.start()
    logger.info("Luồng quét tin pháp luật mới đã chạy (mỗi {}s).", int(interval))


def stop() -> None:
    _STOP.set()
