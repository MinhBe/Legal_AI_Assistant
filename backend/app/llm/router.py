"""LLMRouter — một cửa duy nhất cho mọi lời gọi LLM.

Ý tưởng lấy từ LAWGIC core/llm.py: tự retry lỗi tạm thời (429/5xx/mạng) có
backoff + jitter, ép trả JSON theo schema. Thêm: chọn model theo loại việc
(task) và xoay vòng nhiều key Gemini khi một key lỗi.

Nhà cung cấp chính là Dahl: một key dùng được nhiều model nhỏ. Mỗi lời gọi gửi
song song tới mọi model Dahl và lấy kết quả hợp lệ về sớm nhất (hedging) — vừa
nhanh nhất, vừa né lỗi 429 "hết chỗ" của tài khoản miễn phí.

Các task (sau Dahl là dự phòng theo thứ tự):
  route  / lite  -> Gemini flash-lite  (định tuyến, viết lại truy vấn, tóm tắt ngắn)
  answer         -> Gemini flash       (hỏi đáp có trích dẫn)
  draft / report -> Claude             (soạn thảo, báo cáo dài)  — fallback Gemini
  judge          -> Gemini flash       (chấm eval)
  bulk           -> FPT                 (xử lý dữ liệu hàng loạt) — fallback Gemini

Nhà cung cấp dùng SDK tương thích OpenAI (Dahl, Gemini, FPT) hoặc Anthropic (Claude).
"""

from __future__ import annotations

import json
import random
import re
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

from loguru import logger

from app.config import get_settings
from app.obs import metrics

settings = get_settings()

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_BASE_DELAY = 1.0

# Dahl trả 429 ngay (dưới 1 giây) khi model hết chỗ, nên thử lại dày và lâu hơn
# các nhà cung cấp khác: model nào có chỗ trước thì thắng.
_DAHL_BUSY_RETRIES = 10
_DAHL_BUSY_DELAY = 2.0
_DAHL_TIMEOUT = 180.0
# Mô hình suy luận cần chỗ cho phần nghĩ trước câu trả lời.
_DAHL_MIN_TOKENS = 8192
# Model thua cuộc đua vẫn chạy nốt trong pool; đủ chỗ cho vài người hỏi cùng lúc.
_POOL = ThreadPoolExecutor(max_workers=24, thread_name_prefix="llm-race")

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
# Chữ Hán / kana / Hangul: model nhỏ đôi khi trả lời bằng tiếng Trung dù prompt tiếng Việt
_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯＀-￯]")


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    data: Any = None  # kết quả parse (extract_json), nếu có
    call_id: str | None = None  # id bản ghi đo lường của lời gọi này (app/obs/metrics.py)


class LLMError(RuntimeError):
    pass


def strip_think(text: str) -> str:
    """Bỏ phần suy nghĩ <think>…</think> một số model để lẫn vào câu trả lời.

    Chỉ còn thẻ đóng (thẻ mở nằm trong template) thì lấy phần sau nó; thẻ mở
    chưa đóng nghĩa là model hết token khi còn đang nghĩ -> không có câu trả lời.
    """
    text = _THINK_BLOCK.sub("", text)
    if "</think>" in text:
        text = text.rsplit("</think>", 1)[1]
    if "<think>" in text:
        text = text.split("<think>", 1)[0]
    return text.strip()


def parse_json(text: str) -> dict:
    """Lấy object JSON từ câu trả lời (bỏ rào ```json nếu có). Hỏng -> ValueError."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        raw = raw[4:] if raw.lower().startswith("json") else raw
        raw = raw.strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("không có JSON")
    return json.loads(raw[start : end + 1])


def _status(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )


def _usage(resp: Any) -> tuple[int | None, int | None, int | None]:
    u = getattr(resp, "usage", None)
    rt = getattr(getattr(u, "completion_tokens_details", None), "reasoning_tokens", None)
    return getattr(u, "prompt_tokens", None), getattr(u, "completion_tokens", None), rt


def _record(*, provider: str, model: str, task: str, t0: float, messages, text: str = "",
            resp: Any = None, error: str | None = None, attempts: int = 1) -> str:
    """Ghi một lời gọi (kể cả lời gọi thua cuộc đua). Thiếu usage thì ước lượng và đánh dấu."""
    latency = time.monotonic() - t0
    if resp is None:  # lỗi trước khi có câu trả lời: không có token để tính
        return metrics.record_llm(provider=provider, model=model, task=task, latency_s=latency,
                                  input_tokens=None, output_tokens=None, estimated=False,
                                  attempts=attempts, error=error)
    tin, tout, rt = _usage(resp)
    est = tin is None or tout is None
    if tin is None:
        tin = metrics.estimate_tokens(" ".join(str(m.get("content", "")) for m in messages))
    if tout is None:
        tout = metrics.estimate_tokens(text)
    return metrics.record_llm(provider=provider, model=model, task=task, latency_s=latency,
                              input_tokens=tin, output_tokens=tout, estimated=est,
                              attempts=attempts, error=error, reasoning_tokens=rt)


class LLMRouter:
    def __init__(self) -> None:
        self._gemini_keys = settings.gemini_keys
        self._gemini_idx = 0
        self._dahl_keys = settings.dahl_keys
        self._dahl_idx = 0

    # ---- chọn nhà cung cấp + model theo task ----
    def _plan(self, task: str) -> list[tuple[str, str]]:
        dahl = ("dahl", "*")  # "*" = đua mọi model Dahl
        g_flash = ("gemini", settings.gemini_model)
        g_lite = ("gemini", settings.gemini_model_lite)
        claude = ("claude", settings.anthropic_model)
        fpt = ("fpt", settings.fpt_model)

        table: dict[str, list[tuple[str, str]]] = {
            "route": [dahl, g_lite, g_flash],
            "lite": [dahl, g_lite, g_flash],
            "answer": [dahl, g_flash, g_lite],
            "draft": [dahl, claude, g_flash],
            "report": [dahl, claude, g_flash],
            "judge": [dahl, g_flash, g_lite],
            "bulk": [dahl, fpt, g_flash],
        }
        plan = table.get(task, [dahl, g_flash, g_lite])
        # Lọc nhà cung cấp chưa cấu hình.
        return [(p, m) for (p, m) in plan if self._available(p)]

    def _available(self, provider: str) -> bool:
        return self.available_providers().get(provider, False)

    def available_providers(self) -> dict[str, bool]:
        return {
            "dahl": bool(self._dahl_keys and settings.dahl_model_list),
            "gemini": bool(self._gemini_keys),
            "claude": bool(settings.anthropic_api_key),
            "fpt": bool(settings.fpt_api_key),
        }

    # ---- client ----
    def _openai_client(self, base_url: str, api_key: str, timeout: float = 60.0):
        from openai import OpenAI

        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=timeout)

    def _next_gemini_key(self) -> str:
        key = self._gemini_keys[self._gemini_idx % len(self._gemini_keys)]
        self._gemini_idx += 1
        return key

    def _next_dahl_key(self) -> str:
        key = self._dahl_keys[self._dahl_idx % len(self._dahl_keys)]
        self._dahl_idx += 1
        return key

    # ---- gọi chính ----
    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        task: str = "answer",
        temperature: float = 0.2,
        max_tokens: int | None = None,
        parse: Callable[[str], Any] | None = None,
    ) -> LLMResult:
        """Gọi theo kế hoạch của task. `parse` (nếu có) chạy trên câu trả lời; lỗi
        parse tính như lỗi nhà cung cấp, nên cuộc đua Dahl chỉ nhận kết quả parse được."""
        plan = self._plan(task)
        if not plan:
            raise LLMError(
                "Chưa cấu hình nhà cung cấp LLM nào (thiếu key Dahl/Gemini/Claude/FPT trong .env)."
            )
        last_exc: Exception | None = None
        tried: set[tuple[str, str]] = set()
        for i, (provider, model) in enumerate(plan):
            if (provider, model) in tried:
                continue
            try:
                if provider == "dahl":
                    backup = plan[i + 1] if i + 1 < len(plan) and settings.dahl_hedge_after > 0 else None
                    if backup:
                        tried.add(backup)  # đã chạy trong cuộc đua, lỗi thì không gọi lại
                    return self._race_dahl(messages, temperature, max_tokens, parse, backup, task=task)
                res = self._call(provider, model, messages, temperature, max_tokens, task=task)
                if parse:
                    res.data = parse(res.text)
                metrics.mark_winner(res.call_id)
                return res
            except Exception as exc:  # noqa: BLE001 — thử nhà cung cấp kế tiếp
                logger.warning("LLM {} ({}) lỗi: {}", provider, model, exc)
                last_exc = exc
        raise LLMError(f"Mọi nhà cung cấp đều lỗi: {last_exc}")

    def _call(self, provider, model, messages, temperature, max_tokens, task: str = "answer") -> LLMResult:
        if provider == "claude":
            return self._call_claude(model, messages, temperature, max_tokens, task=task)
        base_url, api_key = self._endpoint(provider)
        return self._call_openai(provider, base_url, api_key, model, messages, temperature, max_tokens,
                                 task=task)

    def _endpoint(self, provider: str) -> tuple[str, str]:
        if provider == "gemini":
            return settings.gemini_base_url, self._next_gemini_key()
        if provider == "fpt":
            return settings.fpt_base_url, settings.fpt_api_key or ""
        raise LLMError(f"Nhà cung cấp không hỗ trợ: {provider}")

    # ---- Dahl: đua song song ----
    def _race_dahl(self, messages, temperature, max_tokens, parse, backup=None, task: str = "answer") -> LLMResult:
        """Đua mọi model Dahl; `backup` (nhà cung cấp kế trong kế hoạch) vào đua muộn."""
        won, dahl_failed = threading.Event(), threading.Event()
        t0 = time.monotonic()
        models = settings.dahl_model_list
        futures = {
            metrics.submit(_POOL, self._call_dahl, m, messages, temperature, max_tokens, parse, won, task): m
            for m in models
        }
        if backup:
            hedge = metrics.submit(_POOL, self._hedge, backup, messages, temperature, max_tokens, parse,
                                   won, dahl_failed, task)
            futures[hedge] = f"{backup[0]} (dự phòng)"
        errors: list[str] = []
        failed_dahl = 0
        for fut in as_completed(futures):
            try:
                res = fut.result()
            except Exception as exc:  # noqa: BLE001 — model khác có thể vẫn thắng
                errors.append(f"{futures[fut]}: {exc}")
                if futures[fut] in models:
                    failed_dahl += 1
                    if failed_dahl == len(models):
                        dahl_failed.set()  # dự phòng khỏi phải chờ hết giờ
                continue
            won.set()
            metrics.mark_winner(res.call_id)
            logger.info("{}: {} thắng sau {:.1f}s", res.provider, res.model, time.monotonic() - t0)
            return res
        raise LLMError("Mọi model Dahl đều lỗi: " + " | ".join(errors))

    def _hedge(self, backup, messages, temperature, max_tokens, parse, won, dahl_failed,
               task: str = "answer") -> LLMResult:
        """Chỉ gọi dự phòng khi sau DAHL_HEDGE_AFTER giây Dahl vẫn chưa trả lời, hoặc đã lỗi hết.

        Dahl miễn phí có lúc cả ba model cùng xếp hàng tới hơn một phút; gọi thêm
        sau một khoảng chờ giới hạn được độ trễ đuôi mà không tốn quota dự phòng
        cho phần lớn câu hỏi Dahl trả lời kịp.
        """
        deadline = time.monotonic() + settings.dahl_hedge_after
        while time.monotonic() < deadline and not dahl_failed.is_set():
            if won.wait(0.1):
                raise LLMError("Dahl đã trả lời")
        if won.is_set():
            raise LLMError("Dahl đã trả lời")
        provider, model = backup
        res = self._call(provider, model, messages, temperature, max_tokens, task=task)
        if parse:
            res.data = parse(res.text)
        return res

    def _call_dahl(self, model, messages, temperature, max_tokens, parse, won, task: str = "answer") -> LLMResult:
        client = self._openai_client(settings.dahl_base_url, self._next_dahl_key(), _DAHL_TIMEOUT)
        extra = {"reasoning_effort": settings.dahl_reasoning_effort} if settings.dahl_reasoning_effort else {}
        for attempt in range(_DAHL_BUSY_RETRIES):
            if won.is_set():
                raise LLMError("đã có model khác trả lời")
            t_att = time.monotonic()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max(max_tokens or 0, _DAHL_MIN_TOKENS),
                    extra_body=extra,
                )
            except Exception as exc:  # noqa: BLE001
                last = _status(exc) != 429 or attempt == _DAHL_BUSY_RETRIES - 1
                if last:
                    _record(provider="dahl", model=model, task=task, t0=t_att, messages=messages,
                            error=str(exc)[:200], attempts=attempt + 1)
                    raise
                time.sleep(random.uniform(0.5, _DAHL_BUSY_DELAY))
                continue
            text = strip_think(resp.choices[0].message.content or "")
            # lời gọi bị loại (rỗng / chữ Hán) vẫn tốn token: phải được ghi, đây là chi phí thật của cuộc đua
            err = None
            if not text:
                err = "rỗng"
            elif _CJK.search(text):
                err = "không phải tiếng Việt"
            cid = _record(provider="dahl", model=model, task=task, t0=t_att, messages=messages,
                          text=text, resp=resp, error=err, attempts=attempt + 1)
            if err == "rỗng":
                raise LLMError("câu trả lời rỗng (hết token khi đang nghĩ?)")
            if err:
                # mọi câu trả lời của ứng dụng đều phải là tiếng Việt: để model khác thắng
                raise LLMError("trả lời không phải tiếng Việt (có chữ Hán/kana/Hangul)")
            return LLMResult(
                text=text, provider="dahl", model=model, data=parse(text) if parse else None, call_id=cid
            )
        raise LLMError("hết lượt chờ chỗ")

    def _call_openai(
        self, provider, base_url, api_key, model, messages, temperature, max_tokens, task: str = "answer"
    ) -> LLMResult:
        def _once(key: str) -> LLMResult:
            client = self._openai_client(base_url, key)
            t0 = time.monotonic()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception as exc:  # noqa: BLE001
                _record(provider=provider, model=model, task=task, t0=t0, messages=messages,
                        error=str(exc)[:200])
                raise
            text = resp.choices[0].message.content or ""
            cid = _record(provider=provider, model=model, task=task, t0=t0, messages=messages,
                          text=text, resp=resp)
            return LLMResult(text=text, provider=provider, model=model, call_id=cid)

        return self._with_retry(lambda: _once(api_key), provider=provider, rotate=(provider == "gemini"))

    def _call_claude(self, model, messages, temperature, max_tokens, task: str = "answer") -> LLMResult:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key, max_retries=0)
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        conv = [m for m in messages if m["role"] != "system"]

        def _once() -> LLMResult:
            t0 = time.monotonic()
            try:
                resp = client.messages.create(
                    model=model,
                    system=system or None,
                    messages=conv,
                    temperature=temperature,
                    max_tokens=max_tokens or 4096,
                )
            except Exception as exc:  # noqa: BLE001
                _record(provider="claude", model=model, task=task, t0=t0, messages=messages,
                        error=str(exc)[:200])
                raise
            text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
            u = getattr(resp, "usage", None)
            tin = getattr(u, "input_tokens", None)
            tout = getattr(u, "output_tokens", None)
            cid = metrics.record_llm(provider="claude", model=model, task=task,
                                     latency_s=time.monotonic() - t0, input_tokens=tin, output_tokens=tout,
                                     estimated=tin is None or tout is None, attempts=1)
            return LLMResult(text=text, provider="claude", model=model, call_id=cid)

        return self._with_retry(_once, provider="claude", rotate=False)

    def extract_json(
        self, messages: list[dict[str, str]], *, task: str = "answer", temperature: float = 0.0
    ) -> dict:
        """Gọi LLM và parse JSON. Retry nhích nhiệt độ khi JSON hỏng."""
        for attempt in range(3):
            temp = temperature if attempt == 0 else 0.5
            try:
                return self.chat(messages, task=task, temperature=temp, parse=parse_json).data
            except LLMError as exc:
                logger.warning("JSON lần {} hỏng: {}", attempt + 1, exc)
        raise LLMError("Không parse được JSON từ LLM sau 3 lần.")

    # ---- streaming (Gemini/FPT/Claude stream thật; Dahl trả một lần sau cuộc đua) ----
    def stream(
        self,
        messages: list[dict[str, str]],
        *,
        task: str = "answer",
        temperature: float = 0.2,
    ) -> Iterator[str]:
        plan = self._plan(task)
        for provider, model in plan:
            try:
                if provider == "dahl":
                    # phần <think> chỉ bỏ được khi đã có trọn câu trả lời
                    yield self._race_dahl(messages, temperature, None, None, task=task).text
                    return
                if provider == "claude":
                    yield from self._stream_claude(model, messages, temperature)
                    return
                base_url, api_key = self._endpoint(provider)
                client = self._openai_client(base_url, api_key)
                stream = client.chat.completions.create(
                    model=model, messages=messages, temperature=temperature, stream=True
                )
                for chunk in stream:
                    delta = chunk.choices[0].delta.content if chunk.choices else None
                    if delta:
                        yield delta
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("stream {} lỗi, thử nhà cung cấp kế: {}", provider, exc)
                continue
        raise LLMError("Không stream được từ nhà cung cấp nào.")

    def _stream_claude(self, model, messages, temperature) -> Iterator[str]:
        from anthropic import Anthropic

        client = Anthropic(api_key=settings.anthropic_api_key, max_retries=0)
        system = "\n".join(m["content"] for m in messages if m["role"] == "system")
        conv = [m for m in messages if m["role"] != "system"]
        with client.messages.stream(
            model=model, system=system or None, messages=conv,
            temperature=temperature, max_tokens=4096,
        ) as s:
            yield from s.text_stream

    # ---- retry ----
    def _with_retry(self, call, *, provider: str, rotate: bool) -> LLMResult:
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return call()
            except Exception as exc:  # noqa: BLE001
                status = _status(exc)
                transient = status in _RETRYABLE_STATUS or status is None
                if not transient or attempt == _MAX_ATTEMPTS - 1:
                    raise
                delay = random.uniform(0, _BASE_DELAY * (2 ** attempt))  # full jitter
                logger.info("retry {} (lần {}/{}) sau {:.1f}s", provider, attempt + 1, _MAX_ATTEMPTS, delay)
                if rotate and self._gemini_keys:
                    # Lần sau dùng key khác; _endpoint sẽ tự lấy key kế tiếp.
                    pass
                time.sleep(delay)
        raise LLMError("hết lượt retry")


_ROUTER: LLMRouter | None = None


def get_router() -> LLMRouter:
    global _ROUTER
    if _ROUTER is None:
        _ROUTER = LLMRouter()
    return _ROUTER
