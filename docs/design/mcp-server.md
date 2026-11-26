# Máy chủ MCP của Legal Agentic (chỉ đọc)

Cho trợ lý AI bên ngoài (Claude Desktop, Cursor, agent nội bộ) dùng kho Legal Agentic qua chuẩn MCP.
Không ghi DB, không gọi LLM; cập nhật kho vẫn đi qua luồng có người duyệt.

| Công cụ | Việc |
|---|---|
| `search_law(query, as_of?, top_k?, domains?)` | Tìm điều/khoản còn hiệu lực tại ngày `as_of` |
| `get_article(doc_id, article_no, clause_no?)` | Toàn văn một điều/khoản + mốc hiệu lực |
| `law_versions(provision_key)` | Lịch sử phiên bản một điều khoản |
| `in_force(day, doc_id?)` | Điều khoản còn hiệu lực tại một ngày |
| `document_relations(doc_id)` | Sửa đổi / thay thế / hướng dẫn |
| `corpus_freshness(topic?)` | Kho nạp lần cuối, có quá hạn không |
| `search_precedents(query, top_k?)` | Án lệ, bản án gần nghĩa |
| `recent_updates(limit?, labor_only?)` | Tin văn bản mới quét được |

## Chạy

```bash
cd backend
python -m app.mcp_server.server                                   # stdio
python -m app.mcp_server.server --transport streamable-http --port 8765
```

Claude Desktop (`claude_desktop_config.json`):

```json
{ "mcpServers": { "lawvn": {
  "command": "python", "args": ["-m", "app.mcp_server.server"],
  "cwd": "C:/Users/Admin/Documents/RAG/RAG/backend" } } }
```

Cần `DATABASE_URL` như backend. Test: `pytest tests/test_mcp_server.py` (không cần Postgres).
