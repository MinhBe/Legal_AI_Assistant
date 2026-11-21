"""End-to-end with an injected fetcher, so no network is used."""

from __future__ import annotations

from webgather.compliance import ComplianceGate, Policy, SourcePolicy
from webgather.fetch import RawResponse
from webgather.pipeline import collect
from webgather.tool import run_tool


def _fetcher(body: str, status: int = 200):
    def f(url, timeout=20, api_key_header=None):
        return RawResponse(status, body, url)

    return f


def _open_gate():
    pol = Policy([SourcePolicy("faq.example", "test: public FAQ", min_delay=0.0, check_robots=False)])
    return ComplianceGate(policy=pol)


def test_collect_allows_and_deidentifies():
    body = "<title>Hỏi đáp</title><p>Ông Lê Văn An, SĐT 0912345678, hỏi về lương.</p>"
    rec = collect("https://faq.example/q/1", gate=_open_gate(), fetcher=_fetcher(body))
    assert rec.ok
    assert "0912345678" not in rec.text
    assert "Lê Văn An" not in rec.text
    assert "lương" in rec.text
    assert rec.title == "Hỏi đáp"
    assert rec.url_hash


def test_collect_blocks_private_without_fetch():
    called = {"n": 0}

    def f(url, timeout=20, api_key_header=None):
        called["n"] += 1
        return RawResponse(200, "x", url)

    rec = collect("https://www.facebook.com/groups/123", gate=_open_gate(), fetcher=f)
    assert not rec.ok
    assert rec.decision.reason == "private_url"
    assert called["n"] == 0  # never fetched


def test_collect_catches_login_wall_after_fetch():
    rec = collect("https://faq.example/q/2", gate=_open_gate(),
                  fetcher=_fetcher("You must log in to continue", 200))
    assert not rec.ok
    assert rec.decision.reason == "login_wall"


def test_tool_check_action_does_not_fetch():
    out = run_tool({"action": "check", "url": "https://www.facebook.com/groups/9"})
    assert out["ok"] is False
    assert out["decision"]["reason"] == "private_url"


def test_tool_unknown_action():
    assert run_tool({"action": "nope", "url": "https://x/y"})["ok"] is False
