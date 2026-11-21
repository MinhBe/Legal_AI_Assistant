"""Máy chủ MCP chỉ-đọc của LawVN.

Chạy:
    python -m app.mcp_server.server                       # stdio (Claude Desktop, Cursor)
    python -m app.mcp_server.server --transport streamable-http --port 8765

Mọi công cụ chỉ đọc kho; cập nhật kho vẫn qua luồng có người duyệt.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from app.mcp_server import tools

INSTRUCTIONS = (
    "LawVN: kho văn bản pháp luật Việt Nam (lao động là chính) có hiệu lực theo thời điểm, "
    "án lệ/bản án và tin văn bản mới. Chỉ đọc. Luôn trích dẫn đúng `citation`/`doc_name` "
    "trả về, không tự bịa số điều. Dùng `as_of` khi câu hỏi gắn với một ngày cụ thể."
)

from mcp.types import ToolAnnotations

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True,
                            openWorldHint=False)


@contextmanager
def _session() -> Iterator[Any]:
    from app.db.base import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _wrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Bọc hàm thuần `fn(db, ...)` thành công cụ tự mở/đóng phiên DB."""
    import functools
    import inspect

    sig = inspect.signature(fn)
    params = list(sig.parameters.values())[1:]  # bỏ `db`

    @functools.wraps(fn)
    def tool(*args: Any, **kwargs: Any) -> Any:
        with _session() as db:
            return fn(db, *args, **kwargs)

    tool.__signature__ = sig.replace(parameters=params)  # type: ignore[attr-defined]
    tool.__annotations__ = {k: v for k, v in fn.__annotations__.items() if k != "db"}
    return tool


TOOLS: list[tuple[str, Callable[..., Any]]] = [
    ("search_law", tools.search_law),
    ("get_article", tools.get_article),
    ("law_versions", tools.law_versions),
    ("in_force", tools.in_force),
    ("document_relations", tools.document_relations),
    ("corpus_freshness", tools.corpus_freshness),
    ("search_precedents", tools.search_precedents),
    ("recent_updates", tools.recent_updates),
]


def _server_class():
    """mcp 2.x dùng MCPServer; 1.x dùng FastMCP. Hỗ trợ cả hai."""
    try:
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except ImportError:
        from mcp.server.fastmcp import FastMCP

        return FastMCP


def build_server(host: str = "127.0.0.1", port: int = 8765):
    cls = _server_class()
    kwargs: dict[str, Any] = {"name": "lawvn", "instructions": INSTRUCTIONS}
    if cls.__name__ == "FastMCP":
        kwargs.update(host=host, port=port)
    server = cls(**kwargs)
    for name, fn in TOOLS:
        server.tool(name=name, description=(fn.__doc__ or "").strip(),
                    annotations=READ_ONLY)(_wrap(fn))
    return server


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="LawVN MCP server (read-only)")
    ap.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args(argv)
    server = build_server(a.host, a.port)
    if a.transport == "stdio" or _server_class().__name__ == "FastMCP":
        server.run(transport=a.transport)
    else:
        server.run(transport=a.transport, host=a.host, port=a.port)


if __name__ == "__main__":
    main()
