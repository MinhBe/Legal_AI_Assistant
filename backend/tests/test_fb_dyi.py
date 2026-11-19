"""tools/fb_dyi.py: bản xuất DYI Facebook (JSON) -> video trong inbox + manifest."""

import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))

from fb_dyi import fix_text, import_zip  # noqa: E402


def _moji(s: str) -> str:  # cách Facebook ghi tiếng Việt
    return s.encode("utf-8").decode("latin-1")


def _make_zip(path: Path) -> None:
    posts = [{"timestamp": 1700000000, "data": [{"post": _moji("Hỏi về đất đai")}],
              "attachments": [{"data": [{"media": {
                  "uri": "your_facebook_activity/posts/media/v1.mp4", "title": ""}}]}]}]
    videos = {"videos_v2": [
        {"uri": "your_facebook_activity/posts/media/v1.mp4", "creation_timestamp": 1700000000,
         "description": "khác"},
        {"uri": "your_facebook_activity/posts/media/v2.mp4", "creation_timestamp": 1700000100,
         "description": _moji("Thuế thu nhập cá nhân")}]}
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("your_facebook_activity/posts/your_posts__check_ins__photos_and_videos_1.json",
                    json.dumps(posts))
        zf.writestr("your_facebook_activity/posts/your_videos.json", json.dumps(videos))
        zf.writestr("your_facebook_activity/posts/media/v1.mp4", b"v1")
        zf.writestr("your_facebook_activity/posts/media/v2.mp4", b"v2")
        zf.writestr("your_facebook_activity/posts/media/p.jpg", b"img")
        zf.writestr("../evil.mp4", b"x")  # zip slip: không được ghi ra ngoài


def test_fix_text_mojibake():
    assert fix_text(_moji("Điều 220")) == "Điều 220"
    assert fix_text("Điều 220") == "Điều 220"


def test_import_zip(tmp_path):
    z = tmp_path / "facebook-minh.zip"
    _make_zip(z)
    inbox = tmp_path / "inbox"
    rows = import_zip(z, inbox)
    by_uri = {r["uri"]: r for r in rows}
    assert by_uri["your_facebook_activity/posts/media/v1.mp4"]["caption"] == "Hỏi về đất đai"
    assert by_uri["your_facebook_activity/posts/media/v2.mp4"]["caption"] == "Thuế thu nhập cá nhân"
    assert all(r["source"] == "facebook-dyi" for r in rows)
    assert sorted(p.name for p in inbox.glob("*.mp4")) == sorted(r["file"] for r in rows)
    assert not (tmp_path / "evil.mp4").exists()
    assert len((inbox / "fb_dyi_manifest.jsonl").read_text(encoding="utf-8").splitlines()) == len(rows)
    assert import_zip(z, inbox) == []  # nhập lại: không trùng
