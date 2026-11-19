"""tools/fb_graph.py với phiên HTTP giả (không gọi mạng)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from fb_graph import fetch  # noqa: E402


class _Resp:
    def __init__(self, body=None, content=b""):
        self.status_code, self._body, self._content = 200, body, content
        self.headers = {"content-type": "application/json"}

    def json(self):
        return self._body

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, params=None, **kw):
        self.calls.append(url)
        if url.endswith("/me/videos"):
            return _Resp({"data": [{"id": "1", "created_time": "2026-11-01T10:00:00+0000",
                                    "description": "Hỏi về thuế", "source": "https://v/1.mp4"}],
                          "paging": {"next": "https://graph/next"}})
        if url == "https://graph/next":
            return _Resp({"data": [{"id": "2", "created_time": "2026-11-02T10:00:00+0000"}]})
        return _Resp(content=b"video")


def test_fetch_pages_downloads_and_dedupes(tmp_path):
    s = _Session()
    rows = fetch(s, "tok", tmp_path)
    assert [r["id"] for r in rows] == ["1"]  # video 2 không có source -> bỏ qua
    assert (tmp_path / rows[0]["file"]).read_bytes() == b"video"
    assert rows[0]["caption"] == "Hỏi về thuế" and rows[0]["source"] == "facebook-graph"
    assert "https://graph/next" in s.calls
    assert fetch(_Session(), "tok", tmp_path) == []  # lần 2: không tải lại


def test_dry_run_writes_nothing(tmp_path):
    rows = fetch(_Session(), "tok", tmp_path, dry_run=True)
    assert len(rows) == 1 and not list(tmp_path.glob("*.mp4"))
