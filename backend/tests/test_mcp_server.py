"""Máy chủ MCP chỉ-đọc: công cụ thuần (module nghiệp vụ giả) + đăng ký trên MCP thật."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest

mcp = pytest.importorskip("mcp")

from app.mcp_server import server, tools  # noqa: E402

SEEN: dict = {}


def _fake_search():
    def search_nodes(db, query, *, top_k, as_of, domains):
        SEEN.update(query=query, top_k=top_k, as_of=as_of, domains=domains)
        return [{"node_id": "blld2019_d35_k1", "doc_id": "blld2019", "display": "Khoản 1 Điều 35 BLLĐ 2019",
                 "article_no": "35", "clause_no": "1", "point_letter": None, "heading": "Quyền đơn phương",
                 "text": "x" * 3000, "score": 0.91234}]

    def search_precedents(db, query, *, top_k):
        return [{"doc_name": "Án lệ 20/2018", "court": "TANDTC", "issued_date": date(2018, 10, 17),
                 "text": "nội dung", "score": 0.8}]

    return SimpleNamespace(search_nodes=search_nodes, search_precedents=search_precedents,
                           doc_name=lambda d: "Bộ luật Lao động 2019")


def _fake_amend():
    return SimpleNamespace(
        versions_for=lambda db, key: [{"provision_key": key, "valid_from": date(2021, 1, 1), "valid_to": None}],
        in_force_at=lambda db, d, doc_id=None: ["a", "b"],
        corpus_freshness=lambda db, today, topic_hint="": {"last_ingest": date(2026, 11, 1), "stale": False},
    )


@pytest.fixture
def fake(monkeypatch):
    mods = {"app.rag.search": _fake_search(), "app.amend.versions": _fake_amend(),
            "app.amend.cascade": _fake_amend()}
    monkeypatch.setattr(tools, "_mod", lambda name: mods[name])
    SEEN.clear()
    return mods


def test_search_law_clamps_and_clips(fake):
    out = tools.search_law(None, "đơn phương chấm dứt", as_of="2024-05-01", top_k=999)
    assert SEEN["top_k"] == tools.MAX_TOP_K
    assert SEEN["as_of"] == date(2024, 5, 1)
    r = out["results"][0]
    assert r["citation"].startswith("Khoản 1 Điều 35")
    assert r["doc_name"] == "Bộ luật Lao động 2019"
    assert len(r["text"]) == tools.MAX_TEXT + 1 and r["score"] == 0.9123


def test_search_law_defaults_to_today_and_rejects_bad_input(fake):
    assert tools.search_law(None, "lương")["as_of"] == date.today().isoformat()
    with pytest.raises(ValueError):
        tools.search_law(None, "  ")
    with pytest.raises(ValueError):
        tools.search_law(None, "lương", as_of="01/05/2024")


def test_versions_in_force_freshness_are_json(fake):
    v = tools.law_versions(None, "blld2019_d35")
    assert v["versions"][0]["valid_from"] == "2021-01-01"
    assert tools.in_force(None, "2026-01-01")["count"] == 2
    assert tools.corpus_freshness(None, "lương")["last_ingest"] == "2026-11-01"
    p = tools.search_precedents(None, "sa thải")["results"][0]
    assert p["issued_date"] == "2018-10-17"


def test_every_tool_is_registered_read_only():
    s = server.build_server()
    listed = asyncio.run(s.list_tools())
    assert {t.name for t in listed} == {n for n, _ in server.TOOLS}
    for t in listed:
        assert t.annotations.read_only_hint is True
        assert "db" not in t.input_schema.get("properties", {})
        assert t.description


def test_call_tool_end_to_end(fake, monkeypatch):
    from contextlib import contextmanager

    @contextmanager
    def no_db():
        yield None

    monkeypatch.setattr(server, "_session", no_db)
    s = server.build_server()
    res = asyncio.run(s.call_tool("search_law", {"query": "thử việc", "top_k": 2}))
    assert "Khoản 1 Điều 35" in str(res)
    assert SEEN["top_k"] == 2
