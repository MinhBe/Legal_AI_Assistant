"""Registry prompt (V4): v1 phải là nguyên văn đã dùng trước đó; v2 chỉ thêm ví dụ, không sửa v1."""

import hashlib

from app import prompts

# SHA-256 của prompt v1 lấy trước khi chuyển vào registry (kế hoạch V4.1)
V1_SHA256 = "57203e4112a69074c4334ab6be3a9df262e9547b6b15ff6bce1a5b4b620298ed"


def test_v1_is_byte_identical_to_the_original_prompt():
    assert hashlib.sha256(prompts.get("qa_answer", "v1").encode()).hexdigest() == V1_SHA256


def test_v2_is_registered_and_extends_v1():
    assert "v2" in prompts.versions("qa_answer")
    assert prompts.get("qa_answer", "v2").startswith(prompts.get("qa_answer", "v1"))


def test_active_version_follows_settings(monkeypatch):
    monkeypatch.setattr(prompts.get_settings(), "qa_prompt_version", "v2")
    assert prompts.active_version("qa_answer") == "v2"
    assert prompts.get("qa_answer") == prompts.get("qa_answer", "v2")
