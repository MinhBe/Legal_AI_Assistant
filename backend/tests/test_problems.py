"""AU2 + PR1: ghi âm/ghi chú nhóm -> bài toán, công tắc Dahl, nối luật/án lệ, duyệt, gợi ý.

Mô hình và bước chép lời đều là hàm giả; DB thật để kiểm bảng mới, nối luật và dọn dòng.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.agent import qa
from app.agent import guard
from app.auth import tokens
from app.db.models import UploadedFile
from app.gateway.pii import mask
from app.intel import inbox
from app.llm.context import get_cloud_first, get_data_class
from app.main import app
from app.problems import link
from app.problems import service as problems
from app.problems.extract import assert_masked

NAME = "Nguyễn Văn An"
PHONE = "0912345678"
ARTICLES = "khoản 1 Điều 36 Bộ luật Lao động"


def _problem(**over) -> dict:
    item = {
        "title": "Nghỉ việc trước hạn hợp đồng",
        "facts": "Người lao động gọi điện hỏi muốn nghỉ trước hạn hợp đồng.",
        "legal_question": "Phải báo trước bao lâu khi đơn phương chấm dứt hợp đồng?",
        "suggested_approach": "Báo trước 45 ngày và giữ lại văn bản báo trước.",
        "options": [{"name": "Báo trước đủ hạn", "pros": "Đúng luật", "cons": "Chờ lâu"}],
        "cited_articles": [ARTICLES],
        "uncertain_points": ["Chưa rõ loại hợp đồng"],
    }
    item.update(over)
    return item


class FakeRouter:
    """Ghi lại mức dữ liệu, cờ Dahl và văn bản mỗi lời gọi; không gọi mạng."""

    def __init__(self, items: list[dict] | None = None) -> None:
        self.items = items if items is not None else [_problem()]
        self.case_classes: list[str] = []
        self.chat_classes: list[str] = []
        self.chat_cloud: list[bool] = []
        self.texts: list[str] = []

    def extract_json(self, messages, *, task="route", temperature=0.0) -> dict:
        self.case_classes.append(get_data_class())
        return {"cases": []}

    def chat(self, messages, *, task="answer", temperature=0.0, parse=None):
        self.chat_classes.append(get_data_class())
        self.chat_cloud.append(get_cloud_first())
        self.texts.append(messages[-1]["content"])
        body = json.dumps({"problems": self.items}, ensure_ascii=False)
        return SimpleNamespace(text=body, provider="fake", model="fake")


def _segments(on_progress=None) -> list[dict]:
    segs = [
        {"start": 0.0, "end": 4.0, "text": f"Tôi là {NAME}, số điện thoại {PHONE}."},
        {"start": 300.0, "end": 310.0, "text": f"Theo {ARTICLES} thì phải báo trước."},
    ]
    if on_progress is not None:
        for seg in segs:
            on_progress(seg["end"])
    return segs


def _fake_convert(src):
    out = Path(src).with_name(f"{Path(src).stem}-16k.wav")
    out.write_bytes(b"RIFF")
    return out


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # chạy lifespan: create_all tạo case_problem/upload_option
        yield c


@pytest.fixture(autouse=True)
def _tables(client):
    """Mọi test trong tệp đều cần bảng mới, kể cả khi chạy lẻ một test."""


@pytest.fixture
def uploads(client):
    made: list[str] = []
    try:
        yield made
    finally:
        for upload_id in made:
            client.delete(f"/api/uploads/{upload_id}")


@pytest.fixture
def made_problems(db):
    ids: list[str] = []
    try:
        yield ids
    finally:
        if ids:
            db.rollback()
            db.execute(text("DELETE FROM case_problem WHERE id = ANY(:ids)"), {"ids": ids})
            db.commit()


@pytest.fixture
def made_precedents(db):
    keys: list[str] = []
    try:
        yield keys
    finally:
        if keys:
            db.rollback()
            db.execute(
                text("DELETE FROM precedent_catalog WHERE doc_key = ANY(:keys)"),
                {"keys": keys},
            )
            db.commit()


def _audio(monkeypatch, router) -> None:
    monkeypatch.setattr("app.audio.job.convert.to_wav", _fake_convert)
    monkeypatch.setattr("app.audio.job.convert.duration", lambda path: 310.0)
    monkeypatch.setattr(
        "app.audio.job.transcribe.run", lambda wav, on_progress=None: _segments(on_progress)
    )
    monkeypatch.setattr("app.audio.job.get_router", lambda: router)


# ---------- 1. mặc định: mức A, processed_by=local ----------
@pytest.mark.db
def test_audio_job_extracts_problems_locally(client, uploads, db, monkeypatch):
    router = FakeRouter()
    _audio(monkeypatch, router)

    r = client.post(
        "/api/uploads",
        files={"file": ("tu-van-nghi-viec.mp3", b"\x00" * 100)},
        data={"consent": "true"},
    )
    assert r.status_code == 202, r.text
    up = r.json()
    uploads.append(up["upload_id"])
    assert client.get(f"/api/uploads/{up['upload_id']}/job").json()["stage"] == "done"

    db.rollback()
    rows = db.execute(
        text("SELECT title, processed_by, source_ts FROM case_problem WHERE upload_id = :u"),
        {"u": up["upload_id"]},
    ).all()
    assert len(rows) == 2  # một bài toán mỗi đoạn
    assert all(row.processed_by == "local" for row in rows)
    assert all(row.source_ts and "–" in row.source_ts for row in rows)
    assert set(router.case_classes) == {"A"}
    assert set(router.chat_classes) == {"A"}
    assert not any(router.chat_cloud)  # không có lời gọi đám mây nào


# ---------- 2. bật Dahl: mức C, chỉ gửi bản đã che ----------
@pytest.mark.db
def test_allow_dahl_sends_only_the_masked_transcript(client, uploads, db, monkeypatch):
    router = FakeRouter()
    _audio(monkeypatch, router)

    r = client.post(
        "/api/uploads",
        files={"file": ("tu-van-dahl.m4a", b"\x00" * 100)},
        data={"consent": "true", "allow_dahl": "true"},
    )
    assert r.status_code == 202, r.text
    up = r.json()
    uploads.append(up["upload_id"])
    assert client.get(f"/api/uploads/{up['upload_id']}/job").json()["stage"] == "done"

    db.rollback()
    processed = db.execute(
        text("SELECT processed_by FROM case_problem WHERE upload_id = :u"),
        {"u": up["upload_id"]},
    ).scalars().all()
    assert processed and set(processed) == {"dahl"}
    assert set(router.chat_classes) == {"C"} and all(router.chat_cloud)
    assert router.texts
    for sent in router.texts:
        assert NAME not in sent and PHONE not in sent
    assert any("[TÊN_1]" in sent for sent in router.texts)

    masked = mask(f"Tôi là {NAME}, số điện thoại {PHONE}.")
    assert_masked(masked.text, masked.mapping)  # bản đã che: cho qua
    with pytest.raises(ValueError):
        assert_masked(f"Tôi là {NAME}, số {PHONE}.", masked.mapping)  # còn giá trị gốc: chặn


# ---------- 3. không có đồng ý thì không bật được Dahl ----------
def test_allow_dahl_requires_consent(client):
    r = client.post(
        "/api/uploads",
        files={"file": ("ghi-chu.txt", "Nội dung thử.".encode())},
        data={"allow_dahl": "true"},
    )
    assert r.status_code == 422
    assert "đồng ý" in r.json()["detail"]


# ---------- 4. nối luật/án lệ: tối đa 3, đúng ngưỡng ----------
@pytest.mark.db
def test_linking_limits_articles_and_precedents(db, made_precedents):
    question = "sa thải trái pháp luật"
    titles = [
        ("AU2T1", "Án lệ về sa thải trái pháp luật"),
        ("AU2T2", "Sa thải trái pháp luật và bồi thường"),
        ("AU2T3", "Trái pháp luật khi sa thải người lao động"),
        ("AU2T4", "Tranh chấp hợp đồng thuê nhà đất"),
    ]
    for key, title in titles:
        db.execute(
            text(
                "INSERT INTO precedent_catalog (doc_key, number, title, url, file_url,"
                " status, last_checked) VALUES (:k, :n, :t, :u, '', 'dang_ap_dung', now())"
            ),
            {"k": key, "n": key[-1], "t": title, "u": f"https://example.test/{key}"},
        )
    made_precedents.extend(key for key, _ in titles)
    db.commit()

    articles = link.link_articles(db, question)
    assert 0 < len(articles) <= 3
    assert all({"node_id", "display", "score"} <= set(a) for a in articles)

    precedents = link.link_precedents(db, question)
    assert 0 < len(precedents) <= 3
    assert all({"number", "title", "status", "url", "similarity"} <= set(p) for p in precedents)
    assert all(p["similarity"] >= link.PRECEDENT_MIN for p in precedents)
    assert "4" not in [p["number"] for p in precedents]  # bài không liên quan bị loại


# ---------- 5. inbox: ghi âm -> job, ghi chú .txt -> bài toán ----------
def _place(path, data: bytes | str) -> None:
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    old = time.time() - 60
    os.utime(path, (old, old))


@pytest.mark.db
def test_inbox_audio_makes_a_job_and_a_txt_note_makes_problems(
    db, tmp_path, monkeypatch, uploads, made_problems
):
    monkeypatch.setattr("app.audio.job.process_audio", lambda upload_id, data: None)
    router = FakeRouter([_problem(title="Nghỉ phép năm của nhóm", facts="Nhóm hỏi nghỉ phép.")])
    monkeypatch.setattr("app.problems.service.get_router", lambda: router)

    root = tmp_path / "inbox"
    root.mkdir()
    _place(root / "ghi-am-nhom.m4a", b"\x00" * 100)
    _place(
        root / "ghi-chu-nhom.txt",
        "Nhóm bàn sáng nay: chị Hoa hỏi nghỉ phép năm còn mấy ngày, "
        "mọi người đề xuất hỏi luật sư trước khi trả lời.",
    )
    before = set(
        db.execute(text("SELECT id FROM case_problem WHERE source_kind = 'note'")).scalars()
    )

    counts = inbox.scan_inbox(db, root)
    assert counts == {"ingested": 2, "matched": 0, "failed": 0, "skipped": 0}

    db.rollback()
    upload_id = db.execute(
        text("SELECT upload_id FROM uploaded_file WHERE filename = 'ghi-am-nhom.m4a'")
    ).scalar()
    assert upload_id
    uploads.append(upload_id)
    job = db.execute(
        text("SELECT kind, consent FROM upload_job WHERE upload_id = :u"), {"u": upload_id}
    ).one()
    assert job.kind == "audio" and job.consent is True
    assert db.get(UploadedFile, upload_id) is not None

    rows = db.execute(
        text("SELECT id, source_kind, upload_id FROM case_problem WHERE source_kind = 'note'")
    ).all()
    new_rows = [row for row in rows if row.id not in before]
    assert len(new_rows) == 1  # đúng một ghi chú -> một bài toán
    made_problems.extend(row.id for row in new_rows)
    assert new_rows[0].upload_id is None


# ---------- 6. duyệt: chỉ bài đã duyệt vào gợi ý, không vào trích dẫn ----------
class QaRouter:
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id

    def extract_json(self, messages, *, task="route", temperature=0.0) -> dict:
        return {"issues": []}

    def chat(self, messages, *, task="answer", temperature=0.0, parse=None):
        text = json.dumps(
            {"summary": "Theo Điều 36 phải báo trước.", "citation_node_ids": [self.node_id]}
        )
        return SimpleNamespace(
            text=text, data=parse(text) if parse else None, provider="fake", model="fake"
        )


@pytest.mark.db
def test_review_approves_and_hints_use_only_approved(client, db, monkeypatch, made_problems):
    question = f"sa thải trái pháp luật quy trình {time.time_ns() % 1_000_000}"
    item = {"title": question, "facts": "Bị sa thải không có quyết định.", "legal_question": question}
    approved = problems.save(db, [item], source_kind="note")[0]
    pending = problems.save(db, [item], source_kind="note")[0]
    made_problems.extend([approved.id, pending.id])

    token = tokens.issue("admin", "admin")
    r = client.patch(
        f"/api/problems/{approved.id}",
        json={"status": "da_duyet", "lawyer_analysis": "Đúng hướng", "lawyer_verdict": "Duyệt"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "da_duyet"
    assert body["approved_by"] == "admin" and body["approved_at"]

    hint_ids = [p["id"] for p in problems.answer_hints(db, question)["problems"]]
    assert approved.id in hint_ids
    assert pending.id not in hint_ids

    row = db.execute(
        text("SELECT node_id, doc_id FROM legal_node LIMIT 1")
    ).one()
    hit = {"node_id": row.node_id, "doc_id": row.doc_id, "display": "Điều 36", "text": "..."}
    monkeypatch.setattr(qa, "get_router", lambda: QaRouter(row.node_id))
    monkeypatch.setattr(qa, "search_with_history", lambda *a, **k: [hit])
    monkeypatch.setattr(
        qa, "_run_verify", lambda *a, **k: {"ok": True, "checked": 1, "problems": [], "dropped": []}
    )
    monkeypatch.setattr(
        guard, "classify", lambda *a: {"category": guard.LEGAL, "suggested": "", "reason": ""}
    )

    events = list(qa.answer_with_citations(question))
    kinds = [event for event, _ in events]
    assert kinds.index("hints") == kinds.index("verifier") - 1
    hints = next(data for event, data in events if event == "hints")
    assert [p["id"] for p in hints["problems"]] == [approved.id]
    citations = [data["node_id"] for event, data in events if event == "citation"]
    assert citations and set(citations) == {row.node_id}
