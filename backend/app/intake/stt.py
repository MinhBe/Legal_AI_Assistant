"""Chép lời tức thì: PCM int16 16 kHz từ trình duyệt -> đoạn partial/final (voice intake).

Cắt theo năng lượng (VAD đơn giản, không cần thêm gói): một câu kết thúc khi im lặng
>= STT_SILENCE_MS sau khi đã có tiếng nói, hoặc khi câu dài quá STT_MAX_SEGMENT_S. Trong lúc nói,
cứ STT_PARTIAL_EVERY_S thì chép thử phần đang có (partial). Model nhỏ, int8, ít luồng CPU, mỗi lúc
một luồng trực tiếp (máy nhà chạy song song việc khác).

Model: PhoWhisper-large nén (STT_LIVE_MODEL); GPU khi có (STT_LIVE_DEVICE=auto), giải phóng sau
5 phút không có phiên. Sau khi chép, sửa thuật ngữ pháp lý hay nghe nhầm bằng code (legal_fixes).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from app.config import get_settings

settings = get_settings()
RATE = 16000
FRAME = RATE * 30 // 1000  # 30 ms

_MODEL = None
_MODEL_LOCK = threading.Lock()
LIVE_LOCK = threading.Lock()  # một luồng trực tiếp mỗi lúc


def _device() -> tuple[str, str]:
    """(thiết bị, kiểu tính). auto: có GPU thì dùng GPU (chỉ lúc có phiên micro, tự giải phóng)."""
    want = settings.stt_live_device
    if want in ("auto", "cuda"):
        try:
            import ctranslate2

            if ctranslate2.get_cuda_device_count() > 0:
                return "cuda", "int8_float16"
        except Exception:  # noqa: BLE001 — không có CUDA thì về CPU
            pass
        if want == "cuda":
            raise RuntimeError("STT_LIVE_DEVICE=cuda nhưng không thấy GPU")
    return "cpu", "int8"


def _load():
    from pathlib import Path

    from faster_whisper import WhisperModel

    device, compute = _device()
    name = settings.stt_live_model if Path(settings.stt_live_model).exists() else settings.stt_live_fallback
    return WhisperModel(name, device=device, compute_type=compute, cpu_threads=settings.stt_live_threads)


def ensure_loaded() -> None:
    """Nạp model trước khi nhận âm thanh (lần đầu khoảng 30 s trên GPU) để báo "sẵn sàng"."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            _MODEL = _load()


def _whisper(audio: np.ndarray) -> str:
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            _MODEL = _load()
        segs, _ = _MODEL.transcribe(audio, language=settings.audio_language, beam_size=1,
                                    vad_filter=False, condition_on_previous_text=False)
        return legal_fixes(" ".join((s.text or "").strip() for s in segs).strip())


def _fix_pairs() -> list[tuple[str, str]]:
    """Cặp nghe nhầm thuật ngữ pháp lý của prompt v2.1 (KNOWN_FIXES), sửa bằng code, không gọi AI.
    Chỉ lấy cặp một-đích rõ ràng ("a -> b"); cặp có điều kiện ("… or …", "(when …)") để model sửa."""
    from app.problems.spoken_v2 import KNOWN_FIXES

    out = []
    for part in KNOWN_FIXES.split(";"):
        if "->" not in part or "(" in part or " or " in part or "'" in part:
            continue
        srcs, dst = part.split("->", 1)
        for src in srcs.split("/"):
            src = src.strip()
            if src and dst.strip():
                out.append((src, dst.strip()))
    return out


_FIXES: list[tuple[str, str]] | None = None


def legal_fixes(text: str) -> str:
    import re

    global _FIXES
    if _FIXES is None:
        _FIXES = _fix_pairs()
    for src, dst in _FIXES:
        text = re.sub(rf"(?<!\w){re.escape(src)}(?!\w)", dst, text, flags=re.IGNORECASE)
    return text


_IDLE = {"gen": 0}


def unload_when_idle(after_s: float = 300.0) -> None:
    """Giải phóng model chép lời tức thì nếu sau `after_s` giây không có phiên mới (RAM máy nhà)."""
    _IDLE["gen"] += 1
    mine = _IDLE["gen"]

    def drop() -> None:
        global _MODEL
        if _IDLE["gen"] == mine and not LIVE_LOCK.locked():
            with _MODEL_LOCK:
                _MODEL = None
            import gc

            gc.collect()

    t = threading.Timer(after_s, drop)
    t.daemon = True
    t.start()


@dataclass
class LiveSession:
    """Nhận các khối PCM; trả các sự kiện {"type": "partial"|"final", "text", "start", "end"}."""

    transcribe: Callable[[np.ndarray], str] = _whisper
    silence_ms: int = field(default_factory=lambda: settings.stt_silence_ms)
    max_segment_s: float = field(default_factory=lambda: settings.stt_max_segment_s)
    partial_every_s: float = field(default_factory=lambda: settings.stt_partial_every_s)
    threshold: float = 0.012  # RMS của tiếng nói (float trong [-1, 1])

    def __post_init__(self) -> None:
        self.buf = np.zeros(0, dtype=np.float32)  # câu đang nói
        self.pending = np.zeros(0, dtype=np.float32)  # phần lẻ chưa đủ một khung
        self.t = 0.0  # giây đã nhận
        self.seg_start = 0.0
        self.voiced = False
        self.silent_frames = 0
        self.since_partial = 0.0
        self.loud_frames = 0
        self.last_cost = 0.0  # giây máy cần cho lần chép gần nhất

    def _run(self, audio: np.ndarray) -> str:
        import time

        t0 = time.monotonic()
        text = self.transcribe(audio)
        self.last_cost = time.monotonic() - t0
        return text

    def feed(self, pcm16: bytes) -> list[dict]:
        x = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768.0
        self.pending = np.concatenate([self.pending, x])
        events: list[dict] = []
        while len(self.pending) >= FRAME:
            frame, self.pending = self.pending[:FRAME], self.pending[FRAME:]
            self.t += FRAME / RATE
            loud = float(np.sqrt(np.mean(frame * frame))) >= self.threshold
            if not self.voiced:
                if loud:
                    self.voiced, self.seg_start, self.silent_frames = True, self.t - FRAME / RATE, 0
                    self.buf, self.since_partial, self.loud_frames = frame.copy(), 0.0, 1
                continue
            self.buf = np.concatenate([self.buf, frame])
            self.since_partial += FRAME / RATE
            self.silent_frames = 0 if loud else self.silent_frames + 1
            self.loud_frames += int(loud)
            seg_len = len(self.buf) / RATE
            if self.silent_frames * 30 >= self.silence_ms or seg_len >= self.max_segment_s:
                events += self._final()
            # máy chậm hơn lời nói (CPU bận): giãn partial theo thời gian chép thật, không dồn việc
            elif self.since_partial >= max(self.partial_every_s, 2 * self.last_cost):
                self.since_partial = 0.0
                text = self._run(self.buf)
                if text:
                    events.append({"type": "partial", "text": text,
                                   "start": round(self.seg_start, 2), "end": round(self.t, 2)})
        return events

    def _final(self) -> list[dict]:
        audio, start = self.buf, self.seg_start
        self.buf, self.voiced, self.silent_frames = np.zeros(0, dtype=np.float32), False, 0
        if self.loud_frames * FRAME < RATE // 4:  # tiếng nói dưới 0,25 s: tiếng động
            return []
        text = self._run(audio)
        return [{"type": "final", "text": text, "start": round(start, 2),
                 "end": round(self.t, 2)}] if text else []

    def close(self) -> list[dict]:
        return self._final() if self.voiced else []
