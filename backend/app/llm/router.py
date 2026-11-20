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
from app.llm.context import get_answer_lang, get_cloud_first, get_data_class, get_no_local
from app.obs import metrics

settings = get_settings()

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_GEM_LOCK = threading.Lock()
_BASE_DELAY = 1.0

# Dò mô hình trong máy (Ollama): nhớ kết quả 60 s, không dò lúc import.
_LOCAL_CACHE_TTL = 60.0
_LOCAL_CACHE: list = [0.0, None]  # [lần dò trước, có sống không]
_LOCAL_LOCK = threading.Lock()

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
_HANGUL = re.compile(r"[가-힯]")  # chưa hỗ trợ tiếng Hàn: luôn bị loại


def _wrong_script(text: str) -> bool:
    """Chữ Hán/kana chỉ hợp lệ khi câu trả lời phải là tiếng Nhật/Trung (ML1)."""
    if get_answer_lang() in ("ja", "zh"):
        return bool(_HANGUL.search(text))
    return bool(_CJK.search(text))


@dataclass
class LLMResult:
    text: str
    provider: str
    model: str
    data: Any = None  # kết quả parse (extract_json), nếu có
    call_id: str | None = None  # id bản ghi đo lường của lời gọi này (app/obs/metrics.py)


class LLMError(RuntimeError):
    pass


class LocalModelUnavailable(LLMError):
    """Mức A/B không được ra ngoài mà mô hình trong máy không sẵn sàng."""


_LOCAL_DOWN = (
    "Mô hình chạy trong máy chưa sẵn sàng (kiểm tra OLLAMA_BASE_URL), "
    "nên câu hỏi mức A/B không được gửi ra nhà cung cấp bên ngoài."
)


def _probe_local() -> bool:
    """Ollama sống không: GET <OLLAMA_BASE_URL>/models với 2 giây chờ."""
    import httpx

    try:
        resp = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/models", timeout=2.0)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001 — không kết nối được nghĩa là chưa sẵn sàng
        return False


def local_reachable() -> bool:
    """Kết quả dò có nhớ 60 giây (nhiều request không dò lại liên tục)."""
    now = time.monotonic()
    if _LOCAL_CACHE[1] is not None and now - _LOCAL_CACHE[0] < _LOCAL_CACHE_TTL:
        return bool(_LOCAL_CACHE[1])
    with _LOCAL_LOCK:
        now = time.monotonic()
        if _LOCAL_CACHE[1] is not None and now - _LOCAL_CACHE[0] < _LOCAL_CACHE_TTL:
            return bool(_LOCAL_CACHE[1])
        ok = _probe_local()
        _LOCAL_CACHE[:] = [now, ok]
        return ok


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


def _strip_think_stream(chunks: Iterator[str]) -> Iterator[str]:
    """Bỏ khối <think>…</think> khi đang stream, giữ đuôi có thể là nửa thẻ."""
    keep = len("</think>") - 1
    buf, thinking = "", False
    for delta in chunks:
        buf += delta
        out = ""
        while buf:
            tag = "</think>" if thinking else "<think>"
            i = buf.find(tag)
            if i != -1:
                if not thinking:
                    out += buf[:i]
                buf = buf[i + len(tag):]
                thinking = not thinking
                continue
            if thinking:
                buf = buf[-keep:] if len(buf) > keep else buf
            elif len(buf) > keep:
                out += buf[:-keep]
                buf = buf[-keep:]
            break
        if out:
            yield out
    if buf and not thinking:
        yield buf


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


class KeyRotation:
    """Xoay vòng key đám mây theo chỉ số, kèm thời gian nghỉ cho key lỗi (chỉ trong bộ nhớ).

    402 (hết hạn mức) / 401 / 403: cả key nghỉ LONG giây (lỗi của key).
    429, 5xx, mạng / hết giờ: chỉ cặp (key, model) nghỉ SHORT giây, vì trên Dahl đó thường là
    một model đang hết chỗ; model dự phòng vẫn dùng được chính key đó."""

    LONG = 3600.0
    SHORT = 90.0
    _LONG_STATUS = {401, 402, 403}
    _SHORT_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 0
        # khóa: idx (cả key) hoặc (idx, model)
        self._cool_until: dict[int | tuple[int, str], float] = {}

    def order(self, n: int, model: str = "") -> list[int]:
        """Chỉ số key cho một lời gọi: bắt đầu từ key kế tiếp, bỏ key (hoặc key+model) đang nghỉ."""
        if n <= 0:
            return []
        now = time.monotonic()
        with self._lock:
            start = self._next % n
            self._next = start + 1
            return [i for i in ((start + k) % n for k in range(n))
                    if self._cool_until.get(i, 0.0) <= now
                    and self._cool_until.get((i, model), 0.0) <= now]

    def cool(self, idx: int, status: int | None, model: str = "") -> float | None:
        """Cho key nghỉ; trả số giây nghỉ, hoặc None nếu lỗi không do key (đổi key vô ích)."""
        if status in self._LONG_STATUS:
            pause, slot = self.LONG, idx
        elif status is None or status in self._SHORT_STATUS:
            pause, slot = self.SHORT, (idx, model)
        else:
            return None
        with self._lock:
            self._cool_until[slot] = time.monotonic() + pause
        return pause

    def reset(self) -> None:
        with self._lock:
            self._next = 0
            self._cool_until.clear()


_KEYS = KeyRotation()


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
        if not settings.llm_legacy_race:
            return self._tiered_plan()
        return self._legacy_plan(task)

    def _tiered_plan(self) -> list[tuple[str, str]]:
        """Mức A/B chỉ mô hình trong máy; mức C thêm tuyến đám mây (CLOUD_LLM_*) làm bậc thang."""
        level = get_data_class()
        local = ("local", settings.local_model)
        if level in ("A", "B"):
            if not self._available("local"):
                raise LocalModelUnavailable(_LOCAL_DOWN)
            return [local]
        route = settings.cloud_route()
        cloud = [("cloud", m) for m in route.models] if route else []
        if settings.cloud_spread_models and len(cloud) > 1:  # dàn đều lượt đi đầu cho mọi model Dahl
            with _GEM_LOCK:
                self._spin = (getattr(self, "_spin", -1) + 1) % len(cloud)
            cloud = cloud[self._spin:] + cloud[:self._spin]
        plan = cloud + [local] if (get_cloud_first() or settings.cloud_first_for_c) else [local] + cloud
        if (settings.no_local_for_c or get_no_local()) and cloud:
            plan = cloud
        if settings.gemini_for_c and self._gemini_keys:
            gem = [("gemini", settings.gemini_model), ("gemini", settings.gemini_model_lite)]
            self._alt = getattr(self, "_alt", 0) + 1  # xen kẽ ai đi trước để chia tải
            plan = [x for x in plan if x[0] != "local"]
            first = not settings.gemini_fallback_only and self._alt % 2
            plan = (gem + plan if first else plan + gem) + (
                [] if settings.no_local_for_c else [local])
        return [(p, m) for (p, m) in plan if self._available(p)]

    def _legacy_plan(self, task: str) -> list[tuple[str, str]]:
        """Kế hoạch cũ: đua Dahl rồi Gemini/Claude/FPT — chỉ khi LLM_LEGACY_RACE=true."""
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
        providers = {"local": local_reachable(), "cloud": settings.cloud_route() is not None}
        if settings.gemini_for_c:
            providers["gemini"] = bool(self._gemini_keys)
        if settings.llm_legacy_race:
            providers |= {
                "dahl": bool(self._dahl_keys and settings.dahl_model_list),
                "gemini": bool(self._gemini_keys),
                "claude": bool(settings.anthropic_api_key),
                "fpt": bool(settings.fpt_api_key),
            }
        return providers

    # ---- client ----
    def _openai_client(self, base_url: str, api_key: str, timeout: float = 60.0):
        from openai import OpenAI

        return OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=timeout)

    def _next_gemini_key(self) -> str:
        """Dàn trải đều mọi key Gemini (Minh 20/11/2026: không để một tài khoản gánh tải).

        Xoay vòng; mỗi key cách nhau ít nhất GEMINI_KEY_MIN_INTERVAL_S (mặc định 12 s, khoảng
        50 % hạn mức 10 lời/phút của gói miễn phí), tối đa GEMINI_KEY_DAILY_CAP lời/ngày, key dính
        429 nghỉ 120 s. Hết key rảnh thì đợi key sớm nhất."""
        n = len(self._gemini_keys)
        st = self.__dict__.setdefault("_gem", {"last": [0.0] * n, "cool": [0.0] * n,
                                               "count": [0] * n, "day": time.strftime("%Y%m%d")})
        with _GEM_LOCK:
            if st["day"] != time.strftime("%Y%m%d"):
                st["count"], st["day"] = [0] * n, time.strftime("%Y%m%d")
            while True:
                now = time.monotonic()
                ready, soonest = None, None
                for j in range(n):
                    i = (self._gemini_idx + j) % n
                    if st["count"][i] >= settings.gemini_key_daily_cap:
                        continue
                    at = max(st["last"][i] + settings.gemini_key_min_interval_s, st["cool"][i])
                    if at <= now:
                        ready = i
                        break
                    soonest = at if soonest is None else min(soonest, at)
                if ready is not None:
                    break
                if soonest is None:
                    raise LLMError("mọi key Gemini đã hết hạn mức ngày")
                time.sleep(max(0.5, soonest - now))
            self._gemini_idx = ready + 1
            st["last"][ready] = time.monotonic()
            st["count"][ready] += 1
            self._gem_last = ready
            logger.info("gemini key #{} lời thứ {}", ready + 1, st["count"][ready])
        return self._gemini_keys[ready]

    def gemini_usage(self) -> list[int]:
        """Số lời gọi hôm nay theo từng key (theo thứ tự, không lộ giá trị)."""
        return list(self.__dict__.get("_gem", {}).get("count", []))

    def _gemini_cooldown(self, exc: Exception) -> None:
        i = getattr(self, "_gem_last", None)
        if i is not None and _status(exc) == 429 and "_gem" in self.__dict__:
            self._gem["cool"][i] = time.monotonic() + 120

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
                "Chưa cấu hình nhà cung cấp LLM nào (OLLAMA_BASE_URL/LOCAL_MODEL cho mô hình trong máy, "
                "biến có tên CLOUD_LLM_API_KEY_ENV chứa key cho tuyến đám mây)."
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
                self.last_provider = f"{provider}:{model}"
                return res
            except Exception as exc:  # noqa: BLE001 — thử nhà cung cấp kế tiếp
                logger.warning("LLM {} ({}) lỗi ở mức {}: {}", provider, model,
                               get_data_class(), exc)
                last_exc = exc
                if i + 1 < len(plan):
                    logger.info(
                        "nâng bậc: provider={} model={} data_class={} escalated_from={}",
                        plan[i + 1][0], plan[i + 1][1], get_data_class(), provider,
                    )
        if get_data_class() in ("A", "B"):
            raise LocalModelUnavailable(_LOCAL_DOWN) from last_exc
        raise LLMError(f"Mọi nhà cung cấp đều lỗi: {last_exc}")

    def _call(self, provider, model, messages, temperature, max_tokens, task: str = "answer") -> LLMResult:
        if provider == "claude":
            return self._call_claude(model, messages, temperature, max_tokens, task=task)
        if provider == "local":
            return self._call_local(model, messages, temperature, max_tokens, task=task)
        if provider == "cloud":
            return self._call_cloud(model, messages, temperature, max_tokens, task=task)
        base_url, api_key = self._endpoint(provider)
        try:
            return self._call_openai(provider, base_url, api_key, model, messages, temperature,
                                     max_tokens, task=task,
                                     retry=not (provider == "gemini" and settings.gemini_for_c))
        except Exception as exc:
            if provider == "gemini":
                self._gemini_cooldown(exc)
            raise

    def _call_local(self, model, messages, temperature, max_tokens, task: str = "answer") -> LLMResult:
        return self._call_openai("local", settings.ollama_base_url, "ollama", model, messages,
                                 temperature, max_tokens, task=task, timeout=settings.local_timeout)

    def _call_cloud(self, model, messages, temperature, max_tokens, task: str = "answer") -> LLMResult:
        """Xoay vòng key: mỗi lời gọi bắt đầu ở key kế tiếp; key lỗi hạn mức / quá tải / mạng
        bị cho nghỉ rồi thử key sau. Lỗi do chính yêu cầu (400, 404 model...) thì dừng ngay để
        router chuyển sang model dự phòng. Log chỉ ghi chỉ số key, không bao giờ ghi giá trị."""
        route = settings.cloud_route()
        if route is None:
            raise LLMError("tuyến đám mây chưa có key (xem CLOUD_LLM_KEYS_DIR / CLOUD_LLM_API_KEY_ENV)")
        extra = {"reasoning_effort": route.reasoning_effort} if route.reasoning_effort else None
        order = _KEYS.order(len(route.api_keys), model)
        if not order:
            raise LLMError(f"mọi key đám mây đang nghỉ với {model} ({len(route.api_keys)} key)")
        last: Exception | None = None
        for idx in order:
            try:
                res = self._call_openai("cloud", route.base_url, route.api_keys[idx], model, messages,
                                        temperature, max(max_tokens or 0, route.min_tokens) or None,
                                        task=task, timeout=settings.cloud_llm_timeout, extra_body=extra,
                                        retry=False)
            except Exception as exc:  # noqa: BLE001
                status = _status(exc)
                pause = _KEYS.cool(idx, status, model)
                if pause is None:
                    raise  # lỗi của yêu cầu, đổi key cũng vậy
                logger.warning("cloud key #{} ({}) lỗi {} -> nghỉ {:.0f}s, thử key kế",
                               idx, model, status, pause)
                last = exc
                continue
            if not res.text:
                raise LLMError("câu trả lời rỗng (hết token khi đang nghĩ?)")
            if _wrong_script(res.text):
                raise LLMError("trả lời không phải tiếng Việt (có chữ Hán/kana/Hangul)")
            return res
        raise LLMError(f"mọi key đám mây đều lỗi ({len(order)} key): {last}")

    def _endpoint(self, provider: str) -> tuple[str, str]:
        if provider == "local":
            return settings.ollama_base_url, "ollama"
        if provider == "cloud":
            route = settings.cloud_route()
            if route is None:
                raise LLMError("tuyến đám mây chưa có key (xem CLOUD_LLM_KEYS_DIR / CLOUD_LLM_API_KEY_ENV)")
            order = _KEYS.order(len(route.api_keys))  # stream: key kế tiếp không bị nghỉ cả key
            if not order:
                raise LLMError("mọi key đám mây đang nghỉ")
            return route.base_url, route.api_keys[order[0]]
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
            elif _wrong_script(text):
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
        self, provider, base_url, api_key, model, messages, temperature, max_tokens,
        task: str = "answer", timeout: float = 60.0, extra_body: dict | None = None,
        retry: bool = True,
    ) -> LLMResult:
        def _once(key: str) -> LLMResult:
            client = self._openai_client(base_url, key, timeout)
            t0 = time.monotonic()
            try:
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **({"extra_body": extra_body} if extra_body else {}),
                )
            except Exception as exc:  # noqa: BLE001
                _record(provider=provider, model=model, task=task, t0=t0, messages=messages,
                        error=str(exc)[:200])
                raise
            text = resp.choices[0].message.content or ""
            if provider in ("local", "cloud"):
                text = strip_think(text)
            cid = _record(provider=provider, model=model, task=task, t0=t0, messages=messages,
                          text=text, resp=resp)
            return LLMResult(text=text, provider=provider, model=model, call_id=cid)

        if not retry:  # tuyến đám mây tự đổi key khi lỗi, không chờ thử lại cùng một key
            return _once(api_key)
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
        if not plan:
            raise LLMError(
                "Chưa cấu hình nhà cung cấp LLM nào (OLLAMA_BASE_URL/LOCAL_MODEL cho mô hình "
                "trong máy, biến có tên CLOUD_LLM_API_KEY_ENV chứa key cho tuyến đám mây)."
            )
        last_exc: Exception | None = None
        for i, (provider, model) in enumerate(plan):
            try:
                if provider == "dahl":
                    # phần <think> chỉ bỏ được khi đã có trọn câu trả lời
                    yield self._race_dahl(messages, temperature, None, None, task=task).text
                    return
                if provider == "claude":
                    yield from self._stream_claude(model, messages, temperature)
                    return
                chunks = self._stream_openai(provider, model, messages, temperature)
                if provider in ("local", "cloud"):
                    chunks = _strip_think_stream(chunks)
                yield from chunks
                return
            except Exception as exc:  # noqa: BLE001
                logger.warning("stream {} ({}) lỗi ở mức {}: {}", provider, model,
                               get_data_class(), exc)
                last_exc = exc
                if i + 1 < len(plan):
                    logger.info(
                        "nâng bậc: provider={} model={} data_class={} escalated_from={}",
                        plan[i + 1][0], plan[i + 1][1], get_data_class(), provider,
                    )
        if get_data_class() in ("A", "B"):
            raise LocalModelUnavailable(_LOCAL_DOWN) from last_exc
        raise LLMError(f"Không stream được từ nhà cung cấp nào: {last_exc}")

    def _stream_openai(self, provider, model, messages, temperature) -> Iterator[str]:
        base_url, api_key = self._endpoint(provider)
        timeout = {"local": settings.local_timeout, "cloud": settings.cloud_llm_timeout}.get(provider, 60.0)
        client = self._openai_client(base_url, api_key, timeout)
        extra: dict = {}
        if provider == "cloud":
            route = settings.cloud_route()
            if route and route.reasoning_effort:
                extra["extra_body"] = {"reasoning_effort": route.reasoning_effort}
        stream = client.chat.completions.create(
            model=model, messages=messages, temperature=temperature, stream=True, **extra
        )
        for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


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
