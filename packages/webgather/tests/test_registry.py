from __future__ import annotations

import pytest

from webgather.core import AUTH, get_source, sources


def test_builtin_sources_present():
    reg = sources()
    assert "public-html" in reg
    assert "user-upload" in reg


def test_auth_values_are_safe():
    # no cookie/session/password is an allowed auth mode
    assert AUTH == {"none", "api_key", "user_upload"}


def test_user_upload_requires_consent():
    with pytest.raises(ValueError):
        get_source("user-upload", paths=["/tmp/x"])  # consent defaults to False
    src = get_source("user-upload", paths=[], consent=True)
    assert src.auth == "user_upload"


def test_public_html_plan():
    src = get_source("public-html", urls=["https://a.example/1", "https://a.example/2"])
    assert list(src.plan()) == ["https://a.example/1", "https://a.example/2"]
