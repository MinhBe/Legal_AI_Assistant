"""Vòng quét tin pháp luật mới (LI1, LI2).

Luồng nền (daemon) 15 phút kiểm tra một lần: nếu lượt quét theo lịch gần nhất đã cách đây
`intel_interval_hours` (mặc định 6 giờ) thì chạy một lượt. Khoá `_LOCK` bảo đảm không bao
giờ có hai lượt chạy cùng lúc; `run_scan` không bao giờ raise (chỉ ghi log và `intel_run.error`).

Trang nào cần JavaScript (anle, vanban.chinhphu) thì mở một Chromium headless cho cả lượt
quét, đóng ở cuối lượt. Fetcher có client tiêm vào (test/offline) thì không mở trình duyệt.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy import select

from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import IntelRun
from app.intel import analyze, fetch, fulltext, sources, store
from app.intel.fetch import BLOCKED_STATUS, Fetcher

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
CHECK_EVERY_S = 15 * 60

_LOCK = threading.Lock()
_STOP = threading.Event()
_THREAD: threading.Thread | None = None


def adapters() -> list[Any]:
    return [
        sources.ThuVienPhapLuat(),
        sources.LuatVietnam(),
        sources.AnLe(),
        sources.VanBanChinhPhu(),
    ]


def is_running() -> bool:
    return _LOCK.locked()


def _fetcher(settings) -> Fetcher:
    listing = tuple(url for adapter in adapters() for url in adapter.listing_urls)
    return Fetcher(settings.intel_user_agent, settings.intel_delay_s, allowed_urls=listing)


def _scan_sources(
    db, settings, fetcher: Fetcher, renderer: fetch.Renderer
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    """Đọc danh sách của từng nguồn, lưu tin mới.

    Trả `({source: {status, found, new}}, {số hiệu: pdf_url})` — bảng PDF của
    vanban.chinhphu dùng để lấy toàn văn cho tin của nguồn khác cùng số hiệu.
    """
    per_source: dict[str, dict[str, Any]] = {}
    pdf_urls: dict[str, str] = {}
    for adapter in adapters():
        status, found, new = "ok", 0, 0
        rendered = getattr(adapter, "needs_render", False) and fetcher.can_render
        for url in adapter.listing_urls[: max(settings.intel_max_pages, 1)]:
            if rendered:
                html = renderer.render(url)
                code = 200 if html else 0
            else:
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
                if data.get("pdf_url"):
                    pdf_urls[(data.get("number") or "").lower()] = data["pdf_url"]
                if store.add_item(db, data):
                    new += 1
        if status == "ok" and getattr(adapter, "last_status", "ok") != "ok":
            status = adapter.last_status  # bị chặn thì giữ `blocked`, không đổi thành needs_browser
        per_source[adapter.name] = {"status": status, "found": found, "new": new}
    return per_source, pdf_urls


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
        fetcher = _fetcher(settings)
        counts_fulltext: dict[str, int] = {}
        with fetch.Renderer(fetcher) as renderer:
            per_source, pdf_urls = _scan_sources(db, settings, fetcher, renderer)
        if settings.intel_fulltext:
            counts_fulltext = fulltext.scan(db, settings, fetcher, pdf_urls)
        counts = analyze.analyse_pending(db)
        store.finish_run(db, run, per_source)
        logger.info(
            "Quét tin mới ({}): {} · toàn văn {} · phân tích {}",
            trigger,
            {name: (v["status"], v["new"]) for name, v in per_source.items()},
            counts_fulltext,
            counts,
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


def _last_scheduled() -> datetime | None:
    """Mốc bắt đầu lượt quét theo lịch gần nhất."""
    db = SessionLocal()
    try:
        return db.scalar(
            select(IntelRun.started_at)
            .where(IntelRun.trigger == "schedule")
            .order_by(IntelRun.started_at.desc())
            .limit(1)
        )
    finally:
        db.close()


def next_run_at(now: datetime | None = None) -> datetime | None:
    """Lượt quét tự động kế tiếp; None = chưa quét theo lịch lần nào."""
    current = now or datetime.now(TZ)
    last = _last_scheduled()
    if last is None:
        return None
    if last.tzinfo is None:  # cột timestamptz nhưng driver có thể trả naive
        last = last.replace(tzinfo=current.tzinfo)
    return last + timedelta(hours=get_settings().intel_interval_hours)


def due_now(now: datetime | None = None) -> bool:
    """Đã đến lượt quét theo lịch chưa?"""
    current = now or datetime.now(TZ)
    upcoming = next_run_at(current)
    return upcoming is None or upcoming <= current


def status() -> dict[str, Any]:
    """Chu kỳ quét và mốc kế tiếp, cho `/api/intel/status` và dòng "lần tới" ở `/tin-moi`."""
    current = datetime.now(TZ)
    upcoming = next_run_at(current) or current
    return {
        "interval_hours": get_settings().intel_interval_hours,
        "next_run_at": upcoming.isoformat(),
    }


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
