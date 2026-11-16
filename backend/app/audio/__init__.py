"""Chép lời tệp ghi âm / ghi hình buổi tư vấn ngay trong máy (AU1, design §7B.3).

Mức A: ffmpeg và faster-whisper chạy trong container, không gọi mạng. Bản chép lời thô
(`<sha>.raw.txt`, còn nguyên dữ liệu cá nhân) chỉ nằm trên đĩa; mọi chỗ khác — toàn văn,
node, LLM — dùng bản đã che dữ liệu cá nhân.
"""

from __future__ import annotations

#: câu xác nhận bắt buộc khi tải tệp ghi âm (đúng chữ hiện trên giao diện)
CONSENT_MSG = "Người được ghi âm đã đồng ý cho dùng bản ghi này"

#: đuôi tệp nhận được; ffmpeg giải mã được tất cả những định dạng này
SUFFIXES = frozenset({".mp3", ".m4a", ".wav", ".ogg", ".webm", ".mp4", ".mov", ".mkv"})


class ConsentRequired(ValueError):
    """Tệp ghi âm mà người tải lên chưa xác nhận có sự đồng ý của người được ghi."""
