"""Danh sách nguồn thu thập: mỗi nguồn một mục, robots.txt quyết định có đọc hay không."""

from app.collect import registry


def test_registry_entries_complete_and_unique():
    ids = [s.id for s in registry.REGISTRY]
    assert len(ids) == len(set(ids))
    for s in registry.REGISTRY:
        assert s.use in ("dùng", "tìm tiếp", "không dùng") and s.why and s.tab


def test_probe_skips_sources_marked_not_used():
    out = registry.probe("quochoi")
    assert out["items"] == [] and out["steps"][0]["ok"] is False


def test_robots_blocked_stops_before_listing(monkeypatch):
    class R:
        def __init__(self, text, code=200):
            self.text, self.status_code = text, code

    class C:
        def __init__(self, *a, **k):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, timeout=0):
            self.calls.append(url)
            return R("User-agent: *\nDisallow: /\n")

    import httpx

    monkeypatch.setattr(httpx, "Client", C)
    out = registry.probe("congbao")
    assert [s["step"] for s in out["steps"]] == ["1. Kiểm robots.txt"] and out["steps"][0]["ok"] is False


def test_status_lists_every_source():
    rows = registry.status(None)
    assert {r["id"] for r in rows} == {s.id for s in registry.REGISTRY}
