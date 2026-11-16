"""Tệp ghi âm/ghi hình -> wav 16 kHz một kênh, và đọc thời lượng (AU1).

ffmpeg/ffprobe chạy bằng subprocess (không qua shell) để không có chỗ cho chèn lệnh.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: ffmpeg giải mã nhanh hơn thời lượng thật nhiều lần; 2x + 60 s là rộng rãi
_TIMEOUT_PER_S = 2.0


class ConversionError(RuntimeError):
    """ffmpeg/ffprobe lỗi hoặc không có trên máy."""


def duration(path: Path) -> float | None:
    """Thời lượng tệp (giây) theo ffprobe; None nếu không đọc được."""
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise ConversionError(f"không đọc được thời lượng: {exc}") from exc
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def to_wav(src: Path) -> Path:
    """Chuyển về wav 16 kHz một kênh (đúng thứ faster-whisper cần)."""
    src = Path(src)
    # đuôi khác .wav để tệp nguồn .wav không bị ghi đè lên chính nó
    out = src.with_name(f"{src.stem}-16k.wav")
    seconds = duration(src) or 0.0
    timeout = 60.0 + _TIMEOUT_PER_S * seconds
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(out)],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except FileNotFoundError as exc:
        raise ConversionError("không tìm thấy ffmpeg") from exc
    except subprocess.TimeoutExpired as exc:
        raise ConversionError(f"ffmpeg chạy quá {int(timeout)} giây") from exc
    if proc.returncode != 0 or not out.exists():
        raise ConversionError(f"ffmpeg lỗi: {proc.stderr.strip()[-300:]}")
    return out
