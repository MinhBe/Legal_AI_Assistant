"""Chép lời tức thì: PCM int16 16 kHz từ trình duyệt -> đoạn partial/final (voice intake).

Cắt theo năng lượng (VAD đơn giản, không cần thêm gói): một câu kết thúc khi im lặng
>= STT_SILENCE_MS sau khi đã có tiếng nói, hoặc khi câu dài quá STT_MAX_SEGMENT_S. Trong lúc nói,
cứ STT_PARTIAL_EVERY_S thì chép thử phần đang có (partial). Model nhỏ, int8, ít luồng CPU, mỗi lúc
một luồng trực tiếp (máy nhà chạy song song việc khác).
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


def _whisper(audio: np.ndarray) -> str:
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel

            _MODEL = WhisperModel(settings.stt_live_model, device="cpu", compute_type="int8",
                                  cpu_threads=settings.stt_live_threads)
        segs, _ = _MODEL.transcribe(audio, language=settings.audio_language, beam_size=1,
                                    vad_filter=False, condition_on_previous_text=False)
        return " ".join((s.text or "").strip() for s in segs).strip()


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
            elif self.since_partial >= self.partial_every_s:
                self.since_partial = 0.0
                text = self.transcribe(self.buf)
                if text:
                    events.append({"type": "partial", "text": text,
                                   "start": round(self.seg_start, 2), "end": round(self.t, 2)})
        return events

    def _final(self) -> list[dict]:
        audio, start = self.buf, self.seg_start
        self.buf, self.voiced, self.silent_frames = np.zeros(0, dtype=np.float32), False, 0
        if self.loud_frames * FRAME < RATE // 4:  # tiếng nói dưới 0,25 s: tiếng động
            return []
        text = self.transcribe(audio)
        return [{"type": "final", "text": text, "start": round(start, 2),
                 "end": round(self.t, 2)}] if text else []

    def close(self) -> list[dict]:
        return self._final() if self.voiced else []
