"""Mức dữ liệu của request hiện tại (design §4, contract G2).

A: tệp khách hàng tải lên, B: có dữ liệu cá nhân, C: câu hỏi thuần pháp lý.
Router đọc mức này để chọn nhà cung cấp; ngoài chat (báo cáo, tổng hợp án lệ)
mặc định "C" vì chỉ gửi văn bản luật.
"""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager

current_data_class: contextvars.ContextVar[str] = contextvars.ContextVar("data_class", default="C")


@contextmanager
def data_class_scope(level: str) -> Iterator[None]:
    token = current_data_class.set(level or "C")
    try:
        yield
    finally:
        current_data_class.reset(token)


def get_data_class() -> str:
    return current_data_class.get()


# Ngôn ngữ câu trả lời của request hiện tại (contract ML1): "vi" | "en" | "ja" | "zh".
current_answer_lang: contextvars.ContextVar[str] = contextvars.ContextVar("answer_lang", default="vi")


@contextmanager
def answer_lang_scope(lang: str) -> Iterator[None]:
    token = current_answer_lang.set(lang or "vi")
    try:
        yield
    finally:
        current_answer_lang.reset(token)


def get_answer_lang() -> str:
    return current_answer_lang.get()


# Cho phép một lượt chat gọi đám mây trước ở mức C (AUTH1: tài khoản VIP).
# Mức A/B vẫn chỉ dùng mô hình trong máy — router không đọc cờ này cho A/B.
current_cloud_first: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "cloud_first", default=False
)


@contextmanager
def cloud_first_scope(on: bool) -> Iterator[None]:
    token = current_cloud_first.set(bool(on))
    try:
        yield
    finally:
        current_cloud_first.reset(token)


def get_cloud_first() -> bool:
    return current_cloud_first.get()


# metrics.submit chỉ chép ContextVar _REQ của nó, nên mức dữ liệu không tự sang
# luồng worker (qa.py gọi guard/generate trong pool). Bọc lại để chép cả context.
# shortcut: sửa tại đây thay vì app/obs/metrics.py vì file đó ngoài phạm vi contract G2;
# gộp vào metrics.submit khi được phép sửa file đó.
from app.obs import metrics as _metrics  # noqa: E402

if not getattr(_metrics, "_copies_full_context", False):

    def _submit(pool, fn, *args, **kwargs):
        return pool.submit(contextvars.copy_context().run, fn, *args, **kwargs)

    _metrics.submit = _submit
    _metrics._copies_full_context = True
