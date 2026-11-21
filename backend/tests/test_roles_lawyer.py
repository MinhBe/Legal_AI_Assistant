"""Vai trò luật sư (21/11/2026)."""

from __future__ import annotations


def test_lawyer_role_reviews_but_cannot_admin():
    from app.auth import roles

    p = roles.perms("lawyer")
    assert {"chat", "calc", "escalate", "review"} <= p
    assert "upload" not in p and "graph" not in p and "dev" not in p
    assert roles.conf("lawyer")["daily"] is None
    assert roles.ACCOUNTS["lawyer1"] == "lawyer"
