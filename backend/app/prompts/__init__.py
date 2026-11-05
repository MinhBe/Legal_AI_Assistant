"""Prompt có version. Đổi nội dung prompt = thêm version mới, không sửa version cũ."""
from __future__ import annotations

from app.config import get_settings
from app.prompts import qa_answer

_REGISTRY: dict[str, dict[str, str]] = {"qa_answer": qa_answer.VERSIONS}


def get(name: str, version: str | None = None) -> str:
    return _REGISTRY[name][version or active_version(name)]


def active_version(name: str) -> str:
    if name == "qa_answer":
        return get_settings().qa_prompt_version
    raise KeyError(name)


def versions(name: str) -> list[str]:
    return sorted(_REGISTRY[name])
