"""Cấu hình tập trung — đọc từ biến môi trường / .env. Không hardcode secret."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class CloudRoute:
    base_url: str
    api_keys: tuple[str, ...] = field(repr=False)  # không bao giờ in key; router xoay vòng theo chỉ số
    models: list[str] = field(default_factory=list)
    reasoning_effort: str = ""
    min_tokens: int = 0
    source: str = ""  # nơi lấy key (thư mục / tên biến), để ghi log

    @property
    def api_key(self) -> str:
        return self.api_keys[0]


def load_key_dir(path: str) -> tuple[str, ...]:
    """Đọc mọi tệp key trong thư mục (bỏ tệp ẩn như .cool-*, .rr-* là trạng thái xoay vòng).

    Mỗi dòng là `TÊN=giá_trị` hoặc chỉ `giá_trị`; bỏ dòng trống và dòng `#`. Không ghi log giá trị."""
    import re
    from pathlib import Path

    root = Path(path)
    if not path or not root.is_dir():
        return ()
    keys: list[str] = []
    for f in sorted(p for p in root.iterdir() if p.is_file() and not p.name.startswith(".")):
        try:
            lines = f.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^(?:export\s+)?[A-Za-z_][A-Za-z0-9_.-]*\s*[=:]\s*(.*)$", line)
            value = (m.group(1) if m else line).strip().strip("'\"")
            if value:
                keys.append(value)
    return tuple(dict.fromkeys(keys))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "postgresql://lawvn:lawvn-dev@localhost:5432/lawvn"

    # LLM chung
    llm_provider: str = "auto"

    # Gemini (OpenAI-compatible)
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    gemini_model: str = "gemini-3.5-flash"
    gemini_model_lite: str = "gemini-3.1-flash-lite"

    # Dahl (OpenAI-compatible): một key dùng được nhiều model, gọi song song lấy kết quả nhanh nhất
    dahl_base_url: str = "https://inference.dahl.global/v1"
    dahl_models: str = (
        "deepseek-ai/DeepSeek-V4-Flash-0731,zai-org/GLM-5.3-Flash,MiniMaxAI/MiniMax-M2.7"
    )
    dahl_reasoning_effort: str = "low"
    # Sau ngần này giây Dahl chưa trả lời thì gọi thêm nhà cung cấp dự phòng vào đua; 0 = tắt
    dahl_hedge_after: float = 15.0

    # Claude
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-opus-5-5"

    # FPT (tùy chọn)
    fpt_base_url: str = "https://mkp-api.fptcloud.com"
    fpt_api_key: str | None = None
    fpt_model: str = "gpt-oss-20b"

    # Mô hình chạy trong máy (Ollama, OpenAI-compatible) — mức dữ liệu A/B chỉ gọi cái này
    ollama_base_url: str = "http://host.docker.internal:11434/v1"
    local_model: str = "qwen2.5:7b"
    local_timeout: float = 120
    # Mô hình đám mây cho mức C (bất kỳ endpoint OpenAI-compatible nào). Đổi nhà cung cấp hay
    # mô hình chỉ cần đổi các biến CLOUD_LLM_* này, không sửa code. Mặc định trỏ vào Dahl.
    cloud_llm_base_url: str = "https://inference.dahl.global/v1"
    cloud_llm_keys_dir: str = "/keys"  # thư mục key (docker-compose mount ./keys chỉ đọc); có key thì xoay vòng
    cloud_llm_api_key_env: str = "Dahl_token_1"  # TÊN biến môi trường chứa key, dùng khi thư mục trống
    # Chọn bằng đo thật 2026-11-16 (3 câu golden A01/A04/A08 qua 5 key Dahl):
    # MiniMax 3/3 đúng, 9-60 s; DeepSeek-V4-Flash đúng khi trả lời nhưng 5/9 lời gọi treo 120 s;
    # GLM 0/5 (429 hết chỗ). Xem docs/huong-dan-doi-mo-hinh.md.
    cloud_llm_model: str = "MiniMaxAI/MiniMax-M2.7"
    cloud_llm_fallback_models: str = "deepseek-ai/DeepSeek-V4-Flash-0731,zai-org/GLM-5.3-Flash"
    cloud_llm_reasoning_effort: str = "low"  # rỗng = không gửi tham số này
    cloud_llm_min_tokens: int = 8192  # model có suy nghĩ cần chỗ cho phần nghĩ + câu trả lời
    cloud_llm_timeout: float = 45  # lời gọi treo trên Dahl không bao giờ về; đổi key sớm thay vì chờ
    cloud_first_for_c: bool = False  # true = mức C gọi đám mây trước, mô hình trong máy làm dự phòng
    # DEEPSEEK_*: tên cũ, chỉ để tương thích; chỉ dùng khi biến chứa key CLOUD_LLM chưa có giá trị
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: str | None = None
    deepseek_model: str = "deepseek-flash"
    # true = kế hoạch cũ (đua Dahl rồi Gemini/Claude/FPT); mặc định dùng định tuyến theo mức
    llm_legacy_race: bool = False

    # Embedding
    embedder: str = "hashing"
    embed_dim: int = 1024

    # Rerank
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    # Truy hồi (V2). Mặc định giữ vector cho tới khi gold set chứng minh hybrid tốt hơn.
    search_mode: str = "vector"          # vector | bm25 | hybrid
    bm25_tokenizer: str = "underthesea"  # underthesea | syllable
    bm25_k1: float = 1.5
    bm25_b: float = 0.75
    hybrid_candidates: int = 30          # số ứng viên mỗi nhánh trước khi gộp
    rrf_k: int = 60
    rerank_top_n: int = 20               # số ứng viên đưa vào reranker

    # Observability
    langfuse_enabled: bool = False
    langfuse_host: str = "http://langfuse:3000"  # tên service trong container, không phải cổng trình duyệt 3002
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    # Phòng thủ chèn lệnh gián tiếp (V5). Mặc định tắt; bật từng lớp để đo riêng.
    inj_prompt_wrap: bool = False      # D3: bọc văn bản truy hồi bằng thẻ dữ liệu trong prompt
    inj_filter_chunks: bool = False    # D1: lọc đoạn truy hồi nghi chèn lệnh trước khi vào prompt
    inj_check_output: bool = False     # D2: kiểm tra đầu ra (URL lạ, lộ prompt, sai ngôn ngữ)
    # Version prompt hỏi đáp đang bật (app/prompts/qa_answer.py). Đổi mặc định chỉ sau khi đo.
    qa_prompt_version: str = "v1"
    # Giá tham chiếu để quy đổi chi phí (USD / 1 triệu token). {} = không tính chi phí.
    llm_prices_json: str = "{}"

    @property
    def gemini_keys(self) -> list[str]:
        """Gom GEMINI_API_KEY_1..10 từ môi trường, bỏ ô trống."""
        import os

        keys = []
        for i in range(1, 11):
            v = os.getenv(f"GEMINI_API_KEY_{i}", "").strip()
            if v:
                keys.append(v)
        # Cho phép cả GEMINI_API_KEY đơn lẻ.
        single = os.getenv("GEMINI_API_KEY", "").strip()
        if single:
            keys.append(single)
        return keys

    @property
    def dahl_keys(self) -> list[str]:
        """Gom Dahl_token_1..10 từ môi trường, không phân biệt hoa thường (DAHL_TOKEN_1 cũng được)."""
        import os

        env = {k.upper(): v.strip() for k, v in os.environ.items()}
        return [env[f"DAHL_TOKEN_{i}"] for i in range(1, 11) if env.get(f"DAHL_TOKEN_{i}")]

    def cloud_route(self) -> CloudRoute | None:
        """Tuyến đám mây cho mức C, hoặc None nếu chưa có key.

        Thứ tự lấy key: mọi key trong CLOUD_LLM_KEYS_DIR (router xoay vòng); thư mục trống thì
        biến môi trường có tên CLOUD_LLM_API_KEY_ENV (không phân biệt hoa thường); cả hai trống
        mà DEEPSEEK_API_KEY có giá trị thì dùng tuyến DeepSeek cũ (tương thích)."""
        import os

        keys = load_key_dir(self.cloud_llm_keys_dir)
        source = self.cloud_llm_keys_dir
        if not keys:
            env = {k.upper(): v.strip() for k, v in os.environ.items()}
            single = env.get(self.cloud_llm_api_key_env.strip().upper(), "")
            keys, source = ((single,) if single else ()), self.cloud_llm_api_key_env
        if keys:
            models = [self.cloud_llm_model.strip()] + [
                m.strip() for m in self.cloud_llm_fallback_models.split(",") if m.strip()]
            return CloudRoute(base_url=self.cloud_llm_base_url, api_keys=keys,
                              models=[m for m in dict.fromkeys(models) if m],
                              reasoning_effort=self.cloud_llm_reasoning_effort.strip(),
                              min_tokens=self.cloud_llm_min_tokens, source=source)
        if self.deepseek_api_key:
            return CloudRoute(base_url=self.deepseek_base_url, api_keys=(self.deepseek_api_key,),
                              models=[self.deepseek_model], reasoning_effort="", min_tokens=0,
                              source="DEEPSEEK_API_KEY")
        return None

    @property
    def dahl_model_list(self) -> list[str]:
        return [m.strip() for m in self.dahl_models.split(",") if m.strip()]

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy cần driver rõ ràng (psycopg3)."""
        url = self.database_url
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
