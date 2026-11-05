"""Cấu hình tập trung — đọc từ biến môi trường / .env. Không hardcode secret."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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
