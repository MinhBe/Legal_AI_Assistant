"""Thư mục inbox cho tệp luật sư tự tải về (LI4).

Minh tải toàn văn bằng tài khoản của mình rồi thả tệp vào một thư mục trên máy
(`./inbox` → `/inbox` trong container). Mỗi lượt quét: nạp tệp qua `upload.service`
(chờ duyệt như tệp tải tay), khớp số hiệu với tin ở `/tin-moi`, ghi `intel_doc` rồi
chuyển tệp sang `done/<ngày>/`. Tệp lỗi sang `failed/` kèm `<tên>.error.txt`.
Tệp đang được ghi (mtime < 10 giây), tệp ẩn và tệp tạm của Office bị bỏ qua.
Không bao giờ raise: lỗi một tệp chỉ tính vào `failed`.
"""

from __future__ import annotations

import re
import shutil
import threading
import time
import unicodedata
from collections import deque
from datetime import date, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.audio import SUFFIXES as AUDIO_SUFFIXES
from app.audio import job as audio_job
from app.config import get_settings
from app.db.models import IntelItem
from app.intel import sources, store
from app.problems import service as problems_service
from app.upload import service as upload_service

EXTS = (".pdf", ".docx", ".doc", ".txt", *AUDIO_SUFFIXES)
MIN_AGE_S = 10  # tệp mới sửa trong 10 giây cuối coi như còn đang ghi
RECENT_MAX = 50

#: kết quả các tệp đã xử lý, mới nhất trước, chỉ giữ trong bộ nhớ tiến trình
_RECENT: deque[dict[str, Any]] = deque(maxlen=RECENT_MAX)
_LAST: dict[str, Any] = {"at": None, "counts": {}}

_DASH = re.compile(r"(?<!\d)(\d{1,6})[-_](\d{4})(?:[-_]([A-Za-zĐđ][A-Za-zĐđ0-9_-]*))?")
_SLASH = re.compile(r"(?<!\d)(\d{1,6})\s*/\s*(\d{4})(?:\s*/\s*([A-Za-zĐđ][A-Za-zĐđ0-9_-]*))?")
_SPACE = re.compile(r"(?:\bnd\b|nghi\s*dinh)\s*(?:so\s*)?(\d{1,6})\s+(\d{4})")
_ND_HINT = re.compile(r"\bnd\b|nghi\s*dinh")


def _fold(text: str) -> str:
    """Chữ để so khớp: bỏ dấu, chữ thường, gộp khoảng trắng."""
    plain = "".join(
        ch for ch in unicodedata.normalize("NFD", text or "") if not unicodedata.combining(ch)
    )
    return " ".join(plain.replace("Đ", "D").replace("đ", "d").split()).lower()


def _make(number: str, year: str, suffix: str = "") -> str:
    suffix = re.sub(r"[\s_]+", "-", (suffix or "").strip()).upper()
    suffix = re.sub(r"\bND\b", "NĐ", suffix).strip("-")
    return f"{number}/{year}/{suffix}" if suffix else f"{number}/{year}"


def normalise_number(value: str) -> str:
    """Chuẩn hoá một số hiệu đã có (`145/2020/ND-CP` → `145/2020/NĐ-CP`)."""
    parts = [p for p in (value or "").split("/") if p.strip()]
    if len(parts) == 3 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
        return _make(parts[0].strip(), parts[1].strip(), parts[2].strip())
    return (value or "").strip()


def number_from_name(filename: str) -> str:
    """Số hiệu trong tên tệp (`399-2026-ND-CP.pdf` → `399/2026/NĐ-CP`); không có thì ""."""
    # bỏ đuôi tệp bằng chuỗi, không dùng Path: tên có thể chứa "/" ("NĐ 399/2026.pdf")
    stem = re.sub(r"\.(?:pdf|docx|doc|txt)$", "", filename or "", flags=re.I)
    folded = _fold(stem)
    for rx in (_DASH, _SLASH):
        found = rx.search(stem)
        if found is None:
            continue
        suffix = found.group(3) or ("NĐ-CP" if _ND_HINT.search(folded) else "")
        return _make(found.group(1), found.group(2), suffix)
    found = _SPACE.search(folded)
    if found:
        return _make(found.group(1), found.group(2), "NĐ-CP")
    return ""


def _files(root: Path) -> list[Path]:
    return [p for p in sorted(root.iterdir()) if p.is_file()]


def _ready(path: Path, now: float) -> bool:
    """Tệp mà lượt quét này sẽ xử lý (không ẩn, đúng đuôi, không còn đang ghi)."""
    name = path.name
    if name.startswith(".") or name.startswith("~$"):
        return False
    if path.suffix.lower() not in EXTS:
        return False
    try:
        return now - path.stat().st_mtime >= MIN_AGE_S
    except OSError:
        return False


def _unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    index = 1
    while True:
        candidate = dest.with_name(f"{dest.stem}-{index}{dest.suffix}")
        if not candidate.exists():
            return candidate
        index += 1


def _move(path: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique(dest_dir / path.name)
    shutil.move(str(path), str(dest))
    return dest


def _match(db, number: str) -> list[IntelItem]:
    """Tin có cùng số hiệu, so khớp không phân biệt hoa thường/dấu."""
    key = _fold(number)
    if not key:
        return []
    rows = db.scalars(select(IntelItem).where(IntelItem.number != "")).all()
    return [item for item in rows if _fold(normalise_number(item.number)) == key]


def _scan_one(db, path: Path) -> dict[str, Any]:
    """Nạp một tệp: văn bản luật → đồ thị, ghi âm → job chép lời, ghi chú nhóm → bài toán."""
    data = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix in AUDIO_SUFFIXES:
        return _scan_audio(db, path, data)
    if _is_note(path, data):
        return _scan_note(db, data)

    number = number_from_name(path.name)
    items = _match(db, number)
    title = items[0].title if items else path.stem

    row = upload_service.save_upload(
        db, data, path.name, title=title, allow_dahl=_inbox_allow_dahl(), set_by="inbox"
    )
    if row.status == "failed":
        raise RuntimeError(row.error or "nạp tệp thất bại")
    if not number:
        text = upload_service.full_text(db, row)[:2000]
        number = normalise_number(sources.doc_number(text))
        items = _match(db, number)

    for item in items:
        store.save_doc(
            db,
            item.id,
            source_url=f"inbox:{path.name}",
            data=data,
            status="ingested",
            upload_id=row.upload_id,
        )
        # để lượt phân tích sau chạy lại với toàn văn vừa nạp
        store.set_status(db, item, "new")
    return {"number": number, "upload_id": row.upload_id, "matched": [i.id for i in items]}


def _inbox_allow_dahl() -> bool:
    """Tệp từ inbox mặc định KHÔNG gửi Dahl; chỉ bật khi cấu hình cho phép."""
    return bool(getattr(get_settings(), "problems_inbox_allow_dahl", False))


def _is_note(path: Path, data: bytes) -> bool:
    """`.txt` không có số hiệu văn bản = ghi chú nhóm, không phải toàn văn luật."""
    if path.suffix.lower() != ".txt":
        return False
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return not normalise_number(sources.doc_number(text))


def _scan_audio(db, path: Path, data: bytes) -> dict[str, Any]:
    """Ghi âm/ghi hình: job chép lời AU1, đồng ý ghi là "inbox", xử lý ở luồng nền."""
    upload_service.precheck(data, path.name, consent=True)
    row, is_new = upload_service.register_upload(db, data, path.name, title=path.stem)
    if is_new:
        audio_job.create(db, row.upload_id, consent=True)
        upload_service.set_option(
            db, row.upload_id, allow_dahl=_inbox_allow_dahl(), set_by="inbox"
        )
        threading.Thread(
            target=audio_job.process_audio,
            args=(row.upload_id, data),
            name=f"inbox-audio-{row.upload_id[:8]}",
            daemon=True,
        ).start()
    return {"number": "", "upload_id": row.upload_id, "matched": []}


def _scan_note(db, data: bytes) -> dict[str, Any]:
    """Ghi chú của nhóm → bài toán (mức A, không tạo tệp tải lên)."""
    text = data.decode("utf-8", errors="replace")
    problems_service.extract_note(db, text)
    return {"number": "", "upload_id": None, "matched": []}


def _push(entry: dict[str, Any]) -> None:
    _RECENT.appendleft(entry)


def scannable(root: str | Path) -> int:
    """Số tệp một lượt quét sắp xử lý (cho panel `/tin-moi`)."""
    try:
        now = time.time()
        return sum(1 for path in _files(Path(root)) if _ready(path, now))
    except OSError:
        return 0


def status(root: str | Path) -> dict[str, Any]:
    """Trạng thái thư mục inbox: chờ bao nhiêu tệp, lượt gần nhất, 50 kết quả cuối."""
    return {
        "dir": str(root),
        "pending_files": scannable(root),
        "last_scan_at": _LAST["at"],
        "last_counts": _LAST["counts"],
        "recent": list(_RECENT),
    }


def scan_inbox(db, root: str | Path) -> dict[str, int]:
    """Một lượt quét thư mục; trả `{ingested, matched, failed, skipped}`. Không bao giờ raise."""
    counts = {"ingested": 0, "matched": 0, "failed": 0, "skipped": 0}
    base = Path(root)
    try:
        now = time.time()
        for path in _files(base):
            if not _ready(path, now):
                counts["skipped"] += 1
                continue
            at = datetime.now().astimezone().isoformat()
            name = path.name
            number = number_from_name(name)
            try:
                result = _scan_one(db, path)
            except Exception as exc:  # noqa: BLE001 — một tệp lỗi không được chặn cả lượt
                counts["failed"] += 1
                logger.warning("Inbox: tệp {} lỗi: {}", name, exc)
                moved_to = ""
                try:
                    db.rollback()
                    moved_to = str(_move(path, base / "failed"))
                    (base / "failed" / f"{name}.error.txt").write_text(
                        f"{exc.__class__.__name__}: {exc}", encoding="utf-8"
                    )
                except Exception:  # noqa: BLE001 — không chuyển được thì để lượt sau
                    pass
                _push(
                    {
                        "filename": name,
                        "number": number,
                        "upload_id": None,
                        "matched_item_ids": [],
                        "moved_to": moved_to,
                        "at": at,
                    }
                )
                continue

            moved_to = str(_move(path, base / "done" / date.today().isoformat()))
            counts["ingested"] += 1
            counts["matched"] += len(result["matched"])
            _push(
                {
                    "filename": name,
                    "number": result["number"],
                    "upload_id": result["upload_id"],
                    "matched_item_ids": result["matched"],
                    "moved_to": moved_to,
                    "at": at,
                }
            )
    except Exception as exc:  # noqa: BLE001 — thư mục biến mất/không đọc được: bỏ lượt
        logger.warning("Inbox: không quét được {}: {}", base, exc)
    _LAST["at"] = datetime.now().astimezone().isoformat()
    _LAST["counts"] = counts
    return counts
