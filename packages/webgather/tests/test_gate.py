"""Gate behaviour: it refuses the right things and allows the right things,
with no network (robots loader and fetcher are injected)."""

from __future__ import annotations

import urllib.robotparser

import pytest

from webgather.compliance import (
    ComplianceGate,
    Policy,
    SourcePolicy,
    R_PRIVATE,
    R_ROBOTS,
    R_RATE,
    R_LOGIN_WALL,
    R_CAPTCHA,
    R_BAD_URL,
    ALLOW,
)


def _robots(text: str):
    def loader(_url: str):
        rp = urllib.robotparser.RobotFileParser()
        rp.parse(text.splitlines())
        return rp

    return loader


def test_private_url_is_blocked_before_anything():
    gate = ComplianceGate()
    for url in (
        "https://www.facebook.com/groups/123456",
        "https://facebook.com/profile.php?id=9",
        "https://www.facebook.com/messages/t/abc",
        "https://instagram.com/direct/inbox/",
    ):
        d = gate.check(url)
        assert not d.allowed and d.reason == R_PRIVATE, url


def test_robots_disallow_blocks():
    gate = ComplianceGate(robots_loader=_robots("User-agent: *\nDisallow: /secret"))
    assert gate.check("https://site.example/secret/x").reason == R_ROBOTS
    assert gate.check("https://site.example/public/x").allowed


def test_bad_scheme():
    assert ComplianceGate().check("ftp://x/y").reason == R_BAD_URL


def test_rate_limit_then_wait_value():
    pol = Policy([SourcePolicy("site.example", "test", min_delay=5.0, check_robots=False)])
    gate = ComplianceGate(policy=pol)
    first = gate.check("https://site.example/a")
    assert first.allowed
    gate.note_fetch("https://site.example/a")
    second = gate.check("https://site.example/b")
    assert not second.allowed and second.reason == R_RATE
    assert 0 < second.wait_seconds <= 5.0


def test_policy_deny_path():
    pol = Policy([SourcePolicy("site.example", "test", deny_paths=[r"/admin"], check_robots=False)])
    gate = ComplianceGate(policy=pol)
    assert not gate.check("https://site.example/admin/x").allowed
    assert gate.check("https://site.example/ok").allowed


def test_inspect_response_catches_walls():
    gate = ComplianceGate()
    assert gate.inspect_response(403, "").reason == R_LOGIN_WALL
    assert gate.inspect_response(429, "").reason == R_RATE
    assert gate.inspect_response(200, "Please log in to continue").reason == R_LOGIN_WALL
    assert gate.inspect_response(200, "<div class='g-recaptcha'>").reason == R_CAPTCHA
    assert gate.inspect_response(200, "<p>Nội dung công khai</p>").allowed


def test_unknown_host_default_allows_but_respects_robots():
    gate = ComplianceGate(robots_loader=lambda _u: None)  # robots unknown
    d = gate.check("https://unknown.example/page")
    assert d.allowed and d.reason == ALLOW


def test_unknown_host_can_be_denied():
    gate = ComplianceGate(policy=Policy(allow_unknown_hosts=False))
    assert not gate.check("https://unknown.example/page").allowed
