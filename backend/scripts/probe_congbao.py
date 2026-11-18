"""Tra Công báo theo từ khoá/số hiệu, in trang + tệp tìm thấy (không tải tệp)."""
import sys
from urllib.parse import quote

from app.config import get_settings
from app.intel import fetch, official
from app.intel.scheduler import _fetcher

settings = get_settings()
fetcher = _fetcher(settings)
with fetch.Renderer(fetcher) as r:
    for kw in sys.argv[1:]:
        url = official.SEARCH_URL.format(keyword=quote(kw))
        html = r.render(url)
        rows = official.parse_list(html, url)
        print(f"== {kw}: {len(rows)} kết quả", flush=True)
        for row in rows[:6]:
            print("  ", row["title"][:150], "|", row["url"], flush=True)
