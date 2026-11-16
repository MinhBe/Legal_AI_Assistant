"""Chat dùng tài liệu đã duyệt (mức A) + danh sách node theo tệp (contract U8).

Toàn bộ nhà cung cấp LLM là giả, không gọi mạng.
"""

from __future__ import annotations

import pytest

from app.agent import pipeline, qa
from app.agent.pipeline import LOCAL_UNAVAILABLE
from app.llm import router as r
from app.llm.context import get_data_class
from tests.test_upload_api import DOCX, _post, client, uploads  # noqa: F401 (fixtures)


def _setup(monkeypatch, *, local_up: bool):
    """Router thật với hai hàm gọi nhà cung cấp giả; trả về (router, calls)."""
    monkeypatch.setattr(r.settings, "llm_legacy_race", False)
    monkeypatch.setattr(r.settings, "local_model", "local-test")
    monkeypatch.setattr(r.settings, "cloud_llm_model", "cloud-test")
    monkeypatch.setattr(r.settings, "cloud_llm_fallback_models", "")
    monkeypatch.setattr(r.settings, "cloud_llm_keys_dir", "")
    monkeypatch.setattr(r.settings, "cloud_llm_api_key_env", "TEST_CLOUD_KEY")
    monkeypatch.setattr(r.settings, "cloud_first_for_c", False)
    monkeypatch.setattr(r.settings, "deepseek_api_key", None)
    monkeypatch.setattr(r, "_KEYS", r.KeyRotation())
    monkeypatch.setenv("TEST_CLOUD_KEY", "k")
    monkeypatch.setattr(r, "_LOCAL_CACHE", [0.0, None])
    monkeypatch.setattr(r, "_probe_local", lambda: local_up)

    answer_json = (
        '{"category": "legal", "summary": "Trả lời thử việc", "sections": [],'
        ' "citation_node_ids": ["up1", "blld2019-d27"]}'
    )
    calls: list[tuple[str, str, str]] = []  # (provider, task, data_class)

    def local(model, messages, temperature, max_tokens, task="answer"):
        calls.append(("local", task, get_data_class()))
        return r.LLMResult(text=answer_json, provider="local", model=model)

    def cloud(model, messages, temperature, max_tokens, task="answer"):
        calls.append(("cloud", task, get_data_class()))
        return r.LLMResult(text=answer_json, provider="cloud", model=model)

    router = r.LLMRouter()
    monkeypatch.setattr(router, "_call_local", local)
    monkeypatch.setattr(router, "_call_cloud", cloud)
    return router, calls


UPLOAD_HIT = {
    "node_id": "up1", "doc_id": "upload-doc", "level": "section",
    "heading": "Thử việc trong hợp đồng mẫu",
    "text": "Thời gian thử việc theo hợp đồng mẫu là 60 ngày.",
    "display": "Đoạn 1 (Hợp đồng mẫu)", "score": 0.9,
    "doc_type": "upload", "title": "Hợp đồng mẫu",
}
LAW_HIT = {
    "node_id": "blld2019-d27", "doc_id": "blld2019", "level": "article",
    "heading": "Thử việc",
    "text": "Thời gian thử việc không quá 60 ngày.",
    "display": "Điều 27 (Bộ luật Lao động 2019)", "score": 0.8,
    "doc_type": "luat",
}


def _offline(monkeypatch) -> None:
    """Không chạm DB: phiên giả, khung thời gian rỗng, verifier bỏ qua."""
    class _Session:
        def close(self):
            pass

    monkeypatch.setattr(qa, "SessionLocal", _Session)
    monkeypatch.setattr(qa, "_timeframe", lambda *a, **k: {})
    monkeypatch.setattr(
        qa, "_run_verify",
        lambda *a, **k: {"ok": True, "checked": 0, "problems": [], "dropped": []},
    )


def _search(monkeypatch, hits):
    seen: list[dict] = []

    def fake(db, query, *, top_k=5, as_of=None, include_uploads=False, **kwargs):
        seen.append({"include_uploads": include_uploads, "as_of": as_of})
        return [dict(h) for h in hits]

    monkeypatch.setattr(qa, "search_nodes", fake)
    return seen


def test_uploads_run_answer_generation_at_level_a(monkeypatch):
    router, calls = _setup(monkeypatch, local_up=True)
    monkeypatch.setattr(qa, "get_router", lambda: router)
    seen = _search(monkeypatch, [UPLOAD_HIT, LAW_HIT])
    _offline(monkeypatch)

    events = list(qa.answer_with_citations("Thời gian thử việc tối đa là bao lâu?", use_uploads=True))
    done = [d for name, d in events if name == "done"][-1]
    assert done["uses_uploads"] is True

    assert seen and seen[0]["include_uploads"] is True
    assert ("answer", "A") in [(task, level) for _, task, level in calls]
    assert not [c for c in calls if c[0] == "cloud"]  # mức A không ra đám mây

    citation = [d for name, d in events if name == "citation"][0]
    assert citation["node_id"] == "up1"
    assert citation["display"].startswith("Tài liệu tải lên: Hợp đồng mẫu")


def test_without_uploads_search_excludes_them_and_keeps_gateway_level(monkeypatch):
    router, calls = _setup(monkeypatch, local_up=True)
    monkeypatch.setattr(qa, "get_router", lambda: router)
    seen = _search(monkeypatch, [LAW_HIT])
    _offline(monkeypatch)

    events = list(qa.answer_with_citations("Thời gian thử việc tối đa là bao lâu?"))
    done = [d for name, d in events if name == "done"][-1]
    assert done["uses_uploads"] is False
    assert seen[0]["include_uploads"] is False
    assert all(level == "C" for _, _, level in calls)


def test_ollama_down_with_upload_hit_reports_local_unavailable(monkeypatch):
    router, calls = _setup(monkeypatch, local_up=False)
    monkeypatch.setattr(pipeline, "get_router", lambda: router)
    monkeypatch.setattr(pipeline, "_data_loaded", lambda: True)
    monkeypatch.setattr(qa, "get_router", lambda: router)
    _search(monkeypatch, [UPLOAD_HIT])
    _offline(monkeypatch)

    events = list(pipeline.run_chat("Thời gian thử việc tối đa là bao lâu?", use_uploads=True))
    text = "".join(d["text"] for name, d in events if name == "token")
    assert "mô hình chạy trong máy" in text
    assert events[-1] == ("done", {"category": "local_unavailable"})
    assert LOCAL_UNAVAILABLE in text
    assert not [c for c in calls if c[0] == "cloud" and c[1] == "answer"]


@pytest.mark.db
def test_upload_nodes_endpoint(client, uploads):  # noqa: F811
    assert client.get("/api/uploads/khong-ton-tai/nodes").status_code == 404

    body = _post(client, DOCX, title="Hợp đồng lao động mẫu")
    uploads.append(body["upload_id"])

    r = client.get(f"/api/uploads/{body['upload_id']}/nodes")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["upload_id"] == body["upload_id"]
    assert data["doc_id"] == body["doc_id"]
    assert data["nodes"]
    for n in data["nodes"]:
        assert set(n) == {"node_id", "level", "heading", "preview", "refs"}
        assert len(n["preview"]) <= 200
        assert isinstance(n["refs"], list)


def test_out_of_corpus_verdict_is_overridden_when_uploads_matched(monkeypatch):
    """Bộ phân loại chỉ biết kho luật cố định; đoạn khớp từ tài liệu đã duyệt thì vẫn trả lời."""
    from app.agent import guard, qa

    monkeypatch.setattr(guard, "classify", lambda *a, **k: {
        "category": guard.OUT_OF_CORPUS, "suggested": "", "reason": "ngoài kho"})
    monkeypatch.setattr(qa, "search_with_history", lambda *a, **k: [
        {"node_id": "up_x-s1", "doc_id": "up_x", "doc_type": "upload", "title": "Án lệ 70",
         "display": "x", "text": "Nội dung án lệ về chấm dứt hợp đồng", "heading": ""}])
    monkeypatch.setattr(qa, "_generate", lambda *a, **k: {
        "summary": "Án lệ nêu việc chấm dứt hợp đồng.", "citation_node_ids": ["up_x-s1"]})
    monkeypatch.setattr(qa, "_run_verify", lambda *a, **k: {
        "ok": True, "checked": 1, "problems": [], "dropped": []})
    events = list(qa.answer_with_citations("Án lệ 70 nói gì?", [], use_uploads=True))
    kinds = [e for e, _ in events]
    assert "citation" in kinds
    assert events[-1][1].get("uses_uploads") is True
