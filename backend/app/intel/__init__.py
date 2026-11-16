"""Tin pháp luật mới (LI1): quét danh sách văn bản mới, phân tích bằng Dahl, luật sư duyệt.

Luồng: `sources` đọc danh sách → `fetch` tải HTML (lịch sự, có robots.txt) → `store` ghi
`intel_item` → `analyze` gọi Dahl (mức C) → `scheduler` chạy mỗi ngày một lượt.
"""
