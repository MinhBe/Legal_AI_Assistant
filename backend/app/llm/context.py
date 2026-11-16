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
