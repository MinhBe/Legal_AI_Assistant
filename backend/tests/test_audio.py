"""Kiểm thử tệp ghi âm/ghi hình -> bản chép lời đã che PII -> ca tư vấn (AU1).

Không dùng model thật, không giải mã âm thanh thật: `convert` và `transcribe` được thay
bằng hàm giả. Riêng bài cuối chạy ffmpeg thật, bỏ qua khi máy không có ffmpeg.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.audio import CONSENT_MSG, SUFFIXES, ConsentRequired, convert
from app.db.models import UploadedFile
from app.llm.context import get_data_class
from app.main import app
from app.upload import service
from app.upload.extract import TooLarge

NAME = "Nguyễn Văn An"
PHONE = "0912345678"
ARTICLES = "khoản 1 Điều 36 Bộ luật Lao động"
LAW_NODE = "blld2019-d36-k1"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:  # chạy lifespan: create_all tạo bảng upload_job
        yield c


@pytest.fixture
def uploads(client):
    """Dọn mọi tệp do test tạo (node, tệp trên đĩa, row, job)."""
    made: list[str] = []
    try:
        yield made
    finally:
        for upload_id in made:
            client.delete(f"/api/uploads/{upload_id}")


class FakeRouter:
    """Trả đúng một ca tư vấn mỗi lần gọi, ghi lại mức dữ liệu lúc gọi."""

    def __init__(self) -> None:
        self.classes: list[str] = []

    def extract_json(self, messages, *, task="answer", temperature=0.0) -> dict:
        self.classes.append(get_data_class())
        return {
            "cases": [
                {
                    "situation": "Người lao động muốn nghỉ việc trước hạn hợp đồng",
                    "question": "Phải báo trước bao lâu?",
                    "answer": f"Theo {ARTICLES} phải báo trước 45 ngày.",
                    "articles": [ARTICLES],
                    # mục hỏng: thiếu "answer" -> phải bị bỏ
                    "situation_thieu": "rác",
                },
                {"situation": "thiếu trường", "question": "?", "answer": ""},
            ]
        }


def fake_segments(on_progress=None) -> list[dict]:
    segs = [
        {"start": 0.0, "end": 4.0, "text": f"Tôi là {NAME}, số điện thoại {PHONE}."},
        {"start": 300.0, "end": 310.0, "text": f"Theo {ARTICLES} thì được nghỉ."},
    ]
    if on_progress is not None:
        for s in segs:
            on_progress(s["end"])
    return segs


def fake_convert(src: Path) -> Path:
    out = Path(src).with_name(f"{Path(src).stem}-16k.wav")
    out.write_bytes(b"RIFF")
    return out


# ---------- 1. precheck ----------
def test_precheck_accepts_audio_and_video_suffixes():
    assert SUFFIXES == {".mp3", ".m4a", ".wav", ".ogg", ".webm", ".mp4", ".mov", ".mkv"}
    for suffix in SUFFIXES:
        service.precheck(b"\x00" * 100, f"ghi-am{suffix}", consent=True)  # không ném lỗi


def test_precheck_rejects_without_consent():
    with pytest.raises(ConsentRequired) as err:
        service.precheck(b"\x00" * 100, "ghi-am.mp3", consent=False)
    assert str(err.value) == CONSENT_MSG


def test_precheck_rejects_over_the_size_limit(monkeypatch):
    monkeypatch.setattr(service.get_settings(), "audio_max_bytes", 10)
    with pytest.raises(TooLarge):
        service.precheck(b"\x00" * 11, "ghi-am.mp3", consent=True)


def test_post_without_consent_is_422_with_the_sentence(client):
    r = client.post("/api/uploads", files={"file": ("ghi-am.mp3", b"\x00" * 10)})
    assert r.status_code == 422
    assert r.json()["detail"] == CONSENT_MSG


# ---------- 2. job trọn vẹn ----------
@pytest.mark.db
def test_job_transcribes_masks_ingests_and_extracts_cases(client, uploads, db, monkeypatch):
    if not db.execute(text("SELECT 1 FROM legal_node WHERE node_id = :n"), {"n": LAW_NODE}).scalar():
        pytest.skip(f"kho thiếu {LAW_NODE}")

    router = FakeRouter()
    monkeypatch.setattr("app.audio.job.convert.to_wav", fake_convert)
    monkeypatch.setattr("app.audio.job.convert.duration", lambda path: 310.0)
    monkeypatch.setattr("app.audio.job.transcribe.run", lambda wav, on_progress=None: fake_segments(on_progress))
    monkeypatch.setattr("app.audio.job.get_router", lambda: router)

    r = client.post(
        "/api/uploads",
        files={"file": ("tu-van-nghi-viec.mp3", b"\x00" * 100)},
        data={"consent": "true"},
    )
    assert r.status_code == 202, r.text
    up = r.json()
    uploads.append(up["upload_id"])

    job = client.get(f"/api/uploads/{up['upload_id']}/job").json()
    assert job["kind"] == "audio"
    assert job["stage"] == "done", job
    assert job["progress"] == 1.0
    assert job["consent"] is True

    done = client.get(f"/api/uploads/{up['upload_id']}").json()
    assert done["status"] == "pending_review", done.get("error")
    assert done["chars"] > 0

    raw = (service.UPLOAD_DIR / f"{up['sha256']}.raw.txt").read_text(encoding="utf-8")
    masked = service.text_path(up["sha256"]).read_text(encoding="utf-8")
    assert NAME in raw and PHONE in raw
    assert NAME not in masked and PHONE not in masked
    assert "[TÊN_1]" in masked
    assert "[00:00:00]" in masked and "[00:05:00]" in masked

    db.rollback()
    rows = db.execute(
        text("SELECT node_id, level, heading, text FROM legal_node WHERE doc_id = :d"),
        {"d": done["doc_id"]},
    ).all()
    assert rows
    for _node_id, _level, _heading, body in rows:
        assert NAME not in body and PHONE not in body

    sections = [r for r in rows if r[1] == "section"]
    assert sections
    assert all(r[3].startswith("Đoạn 00:") for r in sections)
    assert any("Đoạn 00:00:00–" in r[3] for r in sections)
    assert any("Đoạn 00:05:00–" in r[3] for r in sections)

    cases = [r for r in rows if r[1] == "case"]
    assert len(cases) == 2  # một ca mỗi đoạn; mục hỏng bị bỏ
    assert sorted(r[2] for r in cases) == ["Ca tư vấn 1 (00:00:00)", "Ca tư vấn 2 (00:05:00)"]
    assert "Tình huống:" in cases[0][3] and "Căn cứ:" in cases[0][3]

    refs = db.execute(
        text("SELECT to_id FROM node_reference WHERE from_id = ANY(:ids)"),
        {"ids": [r[0] for r in cases]},
    ).scalars().all()
    assert LAW_NODE in refs

    assert router.classes == ["A", "A"]  # mỗi lời gọi đều ở mức A


# ---------- 3. lỗi chép lời ----------
@pytest.mark.db
def test_transcription_failure_marks_upload_and_job_failed(client, uploads, monkeypatch):
    def boom(wav, on_progress=None):
        raise RuntimeError("model chép lời hỏng")

    monkeypatch.setattr("app.audio.job.convert.to_wav", fake_convert)
    monkeypatch.setattr("app.audio.job.convert.duration", lambda path: 2.0)
    monkeypatch.setattr("app.audio.job.transcribe.run", boom)

    r = client.post(
        "/api/uploads",
        files={"file": ("tu-van-hong.m4a", b"\x00" * 100)},
        data={"consent": "true"},
    )
    assert r.status_code == 202, r.text
    up = r.json()
    uploads.append(up["upload_id"])

    job = client.get(f"/api/uploads/{up['upload_id']}/job").json()
    assert job["stage"] == "failed"
    assert "model chép lời hỏng" in job["message"]

    done = client.get(f"/api/uploads/{up['upload_id']}").json()
    assert done["status"] == "failed"
    assert done["error"]


@pytest.mark.db
def test_job_route_is_404_for_documents(client, uploads):
    from app.db.base import SessionLocal

    r = client.post("/api/uploads", files={"file": ("ghi-chu.txt", "Nội dung thử.".encode())})
    assert r.status_code in (200, 202), r.text
    up = r.json()
    uploads.append(up["upload_id"])
    assert client.get(f"/api/uploads/{up['upload_id']}/job").status_code == 404

    db = SessionLocal()
    try:
        assert db.get(UploadedFile, up["upload_id"]) is not None
    finally:
        db.close()


# ---------- 4. ffmpeg thật ----------
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="thiếu ffmpeg")


@needs_ffmpeg
def test_convert_and_duration_with_real_ffmpeg(tmp_path):
    src = tmp_path / "im-lang.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", "2", str(src)],
        capture_output=True, check=True,
    )
    wav = convert.to_wav(src)
    assert wav.exists() and wav != src
    assert Path(src).exists()  # tệp nguồn không bị ghi đè
    assert 1.5 < convert.duration(wav) < 2.5


def test_read_wav_gives_float_samples(tmp_path):
    import wave

    import numpy as np

    from app.audio.transcribe import _read_wav

    p = tmp_path / "x.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(np.array([0, 16384, -32768], dtype=np.int16).tobytes())
    out = _read_wav(p)
    assert out.dtype == np.float32 and list(out) == [0.0, 0.5, -1.0]


def test_remove_upload_deletes_raw_transcript_and_temp_wav(tmp_path, monkeypatch):
    """Xoá tệp ghi âm phải xoá cả bản chép lời thô (mức A) và WAV tạm."""
    from app.upload import service

    monkeypatch.setattr(service, "UPLOAD_DIR", tmp_path)
    sha = "ab" * 32
    raw, wav = tmp_path / f"{sha}.raw.txt", tmp_path / f"{sha}-16k.wav"
    raw.write_text("Nguyễn Văn A 0912345678", encoding="utf-8")
    wav.write_bytes(b"RIFF")

    class Row:
        sha256, filename, doc_id = sha, "x.mp3", None

    class DB:
        def get(self, *a):
            return Row()

        def execute(self, *a):
            return None

        def commit(self):
            return None

    service.remove_upload(DB(), "u1")
    assert not raw.exists() and not wav.exists()
