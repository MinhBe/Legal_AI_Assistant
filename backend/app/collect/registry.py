"""Danh sách nguồn thu thập dữ liệu (trang admin "Thu thập dữ liệu", Minh 20/11/2026).

Mỗi nguồn là MỘT mục `Source` trong REGISTRY: thêm nguồn mới (kể cả tab "Mạng xã hội và cộng đồng"
sau này) chỉ cần thêm một mục, không sửa trang. `status()` đọc số liệu lần chạy gần nhất từ tệp
và bảng sẵn có; `probe()` là "Chạy thử": kiểm robots.txt, đọc trang danh sách, đếm mục, đọc thử
một mục, KHÔNG ghi gì vào kho.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

UA = "LegalAgentic-research-bot/0.1 (nghien cuu phap ly; gian cach 5s)"
DATA = Path("data")


@dataclass
class Source:
    id: str
    tab: str                 # "Văn bản luật" | "Bản án, án lệ" | "Theo dõi văn bản mới" | "Mạng xã hội và cộng đồng"
    name: str
    home: str
    list_url: str            # trang danh sách dùng để chạy thử
    item_pattern: str        # regex đường dẫn mục trong trang danh sách
    use: str                 # "dùng" | "tìm tiếp" | "không dùng"
    why: str                 # lý do (robots, chống bot, điều khoản…)
    script: str              # công cụ thu thập
    pace_s: float = 5.0
    tags: list[str] = field(default_factory=list)


REGISTRY: list[Source] = [
    Source("congbao", "Văn bản luật", "Công báo Chính phủ", "https://congbao.chinhphu.vn/",
           "https://congbao.chinhphu.vn/", r"/van-ban/[a-z0-9-]+\.htm", "dùng",
           "robots.txt: Allow /; trang dựng bằng JavaScript (Chromium)", "scripts/fetch_corpus_ext.py",
           tags=["JS rendering", "PDF/DOCX", "ngày hiệu lực"]),
    Source("vbpl", "Văn bản luật", "Cơ sở dữ liệu văn bản pháp luật", "https://vbpl.vn/",
           "https://vbpl.vn/", r"/[A-Za-z]+/Pages/vbpq-[a-z]+\.aspx\?ItemID=\d+", "tìm tiếp",
           "robots.txt cấm /api/ và /Pages/ ở gốc; chỉ dùng đường dẫn được phép", "(chưa có)"),
    Source("congbobanan", "Bản án, án lệ", "Cổng công bố bản án, quyết định của Toà án",
           "https://congbobanan.toaan.gov.vn/", "https://congbobanan.toaan.gov.vn/",
           r"/2ta\d+t1cvn/chi-tiet-ban-an", "dùng",
           "không có robots.txt (không cấm); chứng chỉ thiếu trung gian: chạy ở máy chủ có kho chứng chỉ hệ điều hành",
           "scripts/fetch_cases.py", tags=["PDF toàn văn", "lọc loại vụ việc", "che PII"]),
    Source("intel", "Theo dõi văn bản mới", "Bộ theo dõi văn bản mới (Công báo, chinhphu.vn)",
           "https://chinhphu.vn/", "https://chinhphu.vn/", r"/[a-z0-9-]+-\d+\.htm", "dùng",
           "robots.txt: Allow /; quét định kỳ", "app/intel/scheduler.py", tags=["định kỳ", "meta luật"]),
    Source("bhxh-hoidap", "Bản án, án lệ", "Hỏi đáp BHXH Việt Nam", "https://baohiemxahoi.gov.vn/hoidap",
           "https://baohiemxahoi.gov.vn/hoidap/Pages/default.aspx", r"/hoidap/[^\"']+", "tìm tiếp",
           "không có robots.txt; danh sách nạp bằng JS SharePoint, cần tìm API công khai", "(chưa có)"),
    Source("moj", "Bản án, án lệ", "Bộ Tư pháp (hỏi đáp pháp luật)", "https://moj.gov.vn/",
           "https://moj.gov.vn/", r"/[a-z0-9-]+/[a-z0-9-]+\.aspx", "tìm tiếp",
           "robots.txt cho phép trừ /cms và ?handler=; có sitemap", "(chưa có)"),
    Source("quochoi", "Văn bản luật", "Quốc hội", "https://quochoi.vn/", "https://quochoi.vn/", r"x^",
           "không dùng", "trả trang JavaScript đặt cookie (thử thách chống bot): không vượt", "—"),
    Source("pbgdpl", "Bản án, án lệ", "Cổng phổ biến giáo dục pháp luật", "https://pbgdpl.gov.vn/",
           "https://pbgdpl.gov.vn/", r"x^", "không dùng", "trả trang từ chối truy cập cho bot", "—"),
    Source("fb-own", "Mạng xã hội và cộng đồng", "Facebook của chính Minh (Graph API, bản xuất DYI)",
           "https://developers.facebook.com/", "", r"x^", "dùng",
           "API chính thức và bản xuất của chủ tài khoản; không cào HTML, không cookie",
           "packages/lawvn-ingest (fb-graph, fb-dyi)", tags=["API chính thức", "có đồng ý"]),
]


def _robots(url: str, client) -> tuple[str, str]:
    """('allowed' | 'blocked' | 'none' | 'error', ghi chú)"""
    base = re.match(r"https?://[^/]+", url).group(0)
    try:
        r = client.get(base + "/robots.txt", timeout=20)
    except Exception as exc:  # noqa: BLE001
        return "error", type(exc).__name__
    if r.status_code != 200 or "user-agent" not in r.text.lower():
        return "none", f"không có robots.txt (HTTP {r.status_code})"
    rp = RobotFileParser()
    rp.parse(r.text.splitlines())
    return ("allowed", "robots.txt cho phép") if rp.can_fetch(UA, url) else ("blocked", "robots.txt cấm")


def _last_run(src: Source) -> dict:
    """Số liệu lần chạy gần nhất, đọc từ tệp/bảng sẵn có (không chạy gì)."""
    out: dict = {}
    if src.id == "congbobanan":
        d = DATA / "raw" / "cases" / "congbobanan"
        files = list(d.glob("*.json")) if d.exists() else []
        out["items"] = len(files)
        if files:
            out["last_at"] = datetime.fromtimestamp(max(f.stat().st_mtime for f in files), timezone.utc).isoformat()
        log = DATA / "raw" / "cases" / "fetch.log"
        if log.exists():
            out["errors"] = sum("Error" in x or "Traceback" in x for x in log.read_text(encoding="utf-8", errors="replace").splitlines())
    elif src.id == "congbao":
        p = DATA / "corpus_ext" / "ingest_wanted.json"
        if p.exists():
            rows = json.loads(p.read_text(encoding="utf-8"))
            out["items"] = sum(r["status"] not in ("failed", "not_found") for r in rows)
            out["errors"] = sum(r["status"] in ("failed",) for r in rows)
            out["last_at"] = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat()
    return out


def status(db=None) -> list[dict]:
    rows = []
    for s in REGISTRY:
        row = asdict(s) | _last_run(s)
        if s.id == "intel" and db is not None:
            from sqlalchemy import text

            r = db.execute(text("select finished_at, error from intel_run order by id desc limit 1")).first()
            if r:
                row["last_at"] = r[0].isoformat() if r[0] else None
                row["errors"] = 1 if r[1] else 0
        if row.get("last_at"):
            age = datetime.now(timezone.utc) - datetime.fromisoformat(row["last_at"])
            row["fresh_days"] = round(age.total_seconds() / 86400, 1)
        rows.append(row)
    return rows


def probe(source_id: str, limit: int = 5) -> dict:
    """Chạy thử: từng bước có thời gian và kết quả; không ghi vào kho."""
    import httpx

    src = next((s for s in REGISTRY if s.id == source_id), None)
    if src is None:
        raise KeyError(source_id)
    steps: list[dict] = []

    def step(name: str, ok: bool, detail: str, t0: float) -> None:
        steps.append({"step": name, "ok": ok, "detail": detail, "ms": round((time.monotonic() - t0) * 1000)})

    if src.use == "không dùng" or not src.list_url:
        return {"source": src.id, "steps": [{"step": "Bỏ qua", "ok": False, "detail": src.why, "ms": 0}],
                "items": []}
    with httpx.Client(headers={"User-Agent": UA}, follow_redirects=True) as client:
        t0 = time.monotonic()
        rstate, note = _robots(src.list_url, client)
        step("1. Kiểm robots.txt", rstate in ("allowed", "none"), note, t0)
        if rstate == "blocked":
            return {"source": src.id, "steps": steps, "items": []}
        time.sleep(src.pace_s)
        t0 = time.monotonic()
        try:
            r = client.get(src.list_url, timeout=40)
            links = sorted(set(re.findall(src.item_pattern, r.text)))[:limit]
            step("2. Đọc trang danh sách", r.status_code == 200,
                 f"HTTP {r.status_code}, {len(r.text) // 1024} KB, {len(links)} mục khớp mẫu", t0)
        except Exception as exc:  # noqa: BLE001 — báo đúng lỗi (TLS, hết giờ…)
            step("2. Đọc trang danh sách", False, f"{type(exc).__name__}: {str(exc)[:160]}", t0)
            return {"source": src.id, "steps": steps, "items": []}
        items = []
        if links:
            time.sleep(src.pace_s)
            t0 = time.monotonic()
            url = urljoin(src.list_url, links[0])
            try:
                d = client.get(url, timeout=40)
                title = re.search(r"<title>(.*?)</title>", d.text, re.S | re.I)
                items.append({"url": url, "title": (title.group(1).strip() if title else "")[:160],
                              "http": d.status_code})
                step("3. Đọc thử mục đầu", d.status_code == 200, items[0]["title"] or url, t0)
            except Exception as exc:  # noqa: BLE001
                step("3. Đọc thử mục đầu", False, f"{type(exc).__name__}: {str(exc)[:160]}", t0)
        items += [{"url": urljoin(src.list_url, x)} for x in links[1:]]
        steps.append({"step": "4. Che PII, chờ duyệt", "ok": True,
                      "detail": "chạy thử không ghi vào kho; lần chạy thật: che PII rồi vào /upload chờ duyệt",
                      "ms": 0})
    return {"source": src.id, "steps": steps, "items": items}
