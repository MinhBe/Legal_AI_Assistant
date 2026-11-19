import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import lawvn_ingest.core as core  # noqa: E402
from lawvn_ingest import Item, get_adapter, ingest  # noqa: E402
from lawvn_ingest.adapters.fb_dyi import fix_text  # noqa: E402
from lawvn_ingest.adapters.fb_graph import FacebookGraph  # noqa: E402


class Dummy:
    name = "dummy"

    def __init__(self, consent="own"):
        self.consent, self.fetched = consent, []

    def list_items(self, since=None):
        yield Item(id="a", source="dummy", consent=self.consent, posted_at="2026-01-01T00:00:00+00:00")
        yield Item(id="b", source="dummy", consent=self.consent, posted_at="2026-06-01T00:00:00+00:00")
        yield Item(id="b", source="dummy", consent=self.consent)  # same (source,id) in one listing

    def fetch(self, item, out_dir):
        self.fetched.append(item.id)
        p = Path(out_dir) / f"{core.stem_for(item)}.mp4"
        p.write_bytes(b"x")
        return p


class _EP:
    name, value = "dummy", "x:Dummy"

    def load(self):
        return Dummy


def test_registry_has_builtins_and_entry_points(monkeypatch):
    monkeypatch.setattr(core, "entry_points", lambda group: [_EP()] if group == core.GROUP else [])
    reg = core.adapters()
    assert {"folder", "fb-dyi", "fb-graph", "dummy"} <= set(reg)
    assert isinstance(get_adapter("dummy"), core.Adapter)
    with pytest.raises(KeyError):
        get_adapter("nope")


def test_store_contract_and_dedupe(tmp_path):
    d = Dummy()
    rows = ingest(d, tmp_path)
    assert [r["id"] for r in rows] == ["a", "b"] and d.fetched == ["a", "b"]
    for r in rows:
        meta = json.loads((tmp_path / f"{r['file']}.meta.json").read_text(encoding="utf-8"))
        assert meta["source"] == "dummy" and meta["consent"] == "own"
    assert len((tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    d2 = Dummy()
    assert ingest(d2, tmp_path) == [] and d2.fetched == []


def test_since_and_dry_run(tmp_path):
    d = Dummy()
    rows = ingest(d, tmp_path, since="2026-03-01", dry_run=True)
    assert [r["id"] for r in rows] == ["b"] and d.fetched == [] and not (tmp_path / "manifest.jsonl").exists()


def test_consent_is_enforced(tmp_path):
    with pytest.raises(ValueError):
        ingest(Dummy(consent="scraped"), tmp_path)


def test_folder_adapter(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "clip one.mp4").write_bytes(b"v")
    (src / "notes.txt").write_text("x")
    rows = ingest(get_adapter("folder", path=str(src), consent="licensed"), tmp_path / "inbox")
    assert len(rows) == 1 and rows[0]["consent"] == "licensed"
    assert (tmp_path / "inbox" / rows[0]["file"]).read_bytes() == b"v"


def _moji(s):
    return s.encode("utf-8").decode("latin-1")


def test_fb_dyi_adapter(tmp_path):
    assert fix_text(_moji("Điều 220")) == "Điều 220" and fix_text("Điều 220") == "Điều 220"
    posts = [{"timestamp": 1700000000, "data": [{"post": _moji("Hỏi về đất đai")}],
              "attachments": [{"data": [{"media": {"uri": "a/posts/media/v1.mp4"}}]}]}]
    videos = {"videos_v2": [
        {"uri": "a/posts/media/v1.mp4", "creation_timestamp": 1700000000, "description": "khác"},
        {"uri": "a/posts/media/v2.mp4", "creation_timestamp": 1700000100,
         "description": _moji("Thuế thu nhập cá nhân")}]}
    z = tmp_path / "facebook-minh.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a/posts/your_posts__check_ins__photos_and_videos_1.json", json.dumps(posts))
        zf.writestr("a/posts/your_videos.json", json.dumps(videos))
        zf.writestr("a/posts/media/v1.mp4", b"v1")
        zf.writestr("a/posts/media/v2.mp4", b"v2")
        zf.writestr("../evil.mp4", b"x")
    inbox = tmp_path / "inbox"
    rows = ingest(get_adapter("fb-dyi", path=str(tmp_path)), inbox)
    caps = {r["id"].split(":", 1)[1]: r["caption"] for r in rows}
    assert caps == {"a/posts/media/v1.mp4": "Hỏi về đất đai",
                    "a/posts/media/v2.mp4": "Thuế thu nhập cá nhân"}
    assert all(r["source"] == "facebook-dyi" for r in rows)
    assert not (tmp_path / "evil.mp4").exists()
    assert ingest(get_adapter("fb-dyi", path=str(z)), inbox) == []


class _Resp:
    def __init__(self, body=None, content=b""):
        self.status_code, self._body, self._content, self.text = 200, body, content, ""

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
    def get(self, url, params=None, **kw):
        if url.endswith("/me/videos"):
            return _Resp({"data": [{"id": "1", "created_time": "2026-11-01T10:00:00+0000",
                                    "description": "Hỏi về thuế", "source": "https://v/1.mp4"}],
                          "paging": {"next": "https://graph/next"}})
        if url == "https://graph/next":
            return _Resp({"data": [{"id": "2", "created_time": "2026-11-02T10:00:00+0000"}]})
        return _Resp(content=b"video")


def test_fb_graph_adapter(tmp_path):
    rows = ingest(FacebookGraph(session=_Session(), token="t"), tmp_path)
    assert [r["id"] for r in rows] == ["1"] and rows[0]["caption"] == "Hỏi về thuế"
    assert (tmp_path / rows[0]["file"]).read_bytes() == b"video"
    assert ingest(FacebookGraph(session=_Session(), token="t"), tmp_path) == []
