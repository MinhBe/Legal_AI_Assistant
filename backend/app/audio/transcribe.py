"""Chép lời bằng faster-whisper trong máy (AU1).

Model nạp lười lần đầu và giữ lại cho cả tiến trình: nạp lại mỗi tệp thì quá chậm.
`faster_whisper` được import bên trong hàm để app vẫn khởi động được khi thiếu gói —
lúc đó job báo lỗi rõ ràng thay vì sập cả API.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from app.config import get_settings

settings = get_settings()

_MODEL = None
_MODEL_NAME: str | None = None


def _model():
    global _MODEL, _MODEL_NAME
    name = settings.audio_model
    if _MODEL is None or _MODEL_NAME != name:
        from faster_whisper import WhisperModel  # không cần khi chỉ chạy tệp văn bản

        _MODEL = WhisperModel(
            name, device=settings.audio_device, compute_type=settings.audio_compute
        )
        _MODEL_NAME = name
    return _MODEL


def _read_wav(path: Path):
    """WAV 16-bit mono 16 kHz (đầu ra của convert.to_wav) -> numpy float32 trong [-1, 1]."""
    import wave

    import numpy as np

    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1 or w.getframerate() != 16000:
            raise ValueError("cần WAV 16-bit mono 16 kHz (chạy convert.to_wav trước)")
        frames = w.readframes(w.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def run(wav: Path, on_progress: Callable[[float], None] | None = None) -> list[dict]:
    """Chép lời -> [{"start", "end", "text"}] theo thứ tự thời gian."""
    # Đưa thẳng mảng PCM thay vì đường dẫn: faster-whisper 1.1.1 giải mã bằng PyAV và gọi
    # av.open(metadata_errors=...), tham số mà PyAV 14+ đã bỏ. convert.to_wav đã ra 16 kHz mono.
    segments, _info = _model().transcribe(
        _read_wav(wav), language=settings.audio_language, vad_filter=True
    )
    out: list[dict] = []
    for seg in segments:  # generator: chạy dần, nhờ vậy báo được tiến trình
        out.append({"start": float(seg.start), "end": float(seg.end),
                    "text": (seg.text or "").strip()})
        if on_progress is not None:
            on_progress(float(seg.end))
    return out
