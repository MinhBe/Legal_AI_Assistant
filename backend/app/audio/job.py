"""Tiến trình nền: tệp ghi âm/ghi hình -> bản chép lời đã che PII -> node (AU1).

Thứ tự bắt buộc: chuyển định dạng -> chép lời -> che dữ liệu cá nhân NGAY -> nạp node ->
rút ca tư vấn (mỗi đoạn một lời gọi mô hình trong máy, mức A). Bản thô `<sha>.raw.txt`
giữ nguyên dữ liệu cá nhân, chỉ nằm trên đĩa; mọi thứ khác dùng bản đã che.

Job tự mở session riêng và không bao giờ ném lỗi ra ngoài: lỗi thành trạng thái `failed`
ở cả job lẫn tệp, nếu không row sẽ kẹt mãi ở `processing`.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from app.audio import convert, transcribe
from app.audio.cases import extract as extract_cases
from app.config import get_settings
from app.db.base import SessionLocal
from app.db.models import LegalNode, NodeReference, UploadedFile, UploadJob
from app.gateway.pii import mask
from app.ingestion.references import extract_refs, known_docs_from_db
from app.llm.router import get_router
from app.problems.extract import extract as extract_problems
from app.problems.service import save as save_problems
from app.rag.embeddings import embed_one
from app.upload import service
from app.upload.ingest import ingest_upload, make_doc_id

settings = get_settings()

#: tiến trình ghi vào job tối đa mỗi ngần này giây (ghi DB liên tục thì phí)
PROGRESS_EVERY_S = 5.0


def create(db: Session, upload_id: str, *, consent: bool) -> UploadJob:
    """Tạo dòng tiến trình cho tệp ghi âm/ghi hình; gọi khi nhận tệp."""
    job = db.get(UploadJob, upload_id)
    if job is None:
        job = UploadJob(upload_id=upload_id)
        db.add(job)
    job.kind = "audio"
    job.stage = "converting"
    job.progress = 0.0
    job.message = None
    job.consent = consent
    db.commit()
    return job


def get(db: Session, upload_id: str) -> UploadJob | None:
    return db.get(UploadJob, upload_id)


def to_dict(job: UploadJob) -> dict:
    return {
        "upload_id": job.upload_id,
        "kind": job.kind,
        "stage": job.stage,
        "progress": job.progress,
        "message": job.message,
        "duration_s": job.duration_s,
        "consent": bool(job.consent),
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def process_audio(upload_id: str, data: bytes) -> None:
    """Chạy trọn tiến trình ở nền; không bao giờ ném lỗi ra ngoài."""
    db = SessionLocal()
    try:
        _run(db, upload_id, data)
    except Exception as exc:  # noqa: BLE001 - chạy ở nền, lỗi phải thành trạng thái
        logger.warning("Chép lời tệp {} lỗi: {}", upload_id, exc)
        _fail(db, upload_id, str(exc))
    finally:
        db.close()


def _run(db: Session, upload_id: str, data: bytes) -> None:
    row = db.get(UploadedFile, upload_id)
    if row is None:
        return
    job = db.get(UploadJob, upload_id) or create(db, upload_id, consent=False)

    src = service.stored_path(row.sha256, row.filename)
    service.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    src.write_bytes(data)

    _stage(db, job, "converting", 0.0)
    wav = convert.to_wav(src)
    seconds = convert.duration(wav) or 0.0
    job.duration_s = seconds
    db.commit()

    _stage(db, job, "transcribing", 0.0)
    last = [0.0]

    def on_progress(end: float) -> None:
        now = time.monotonic()
        if seconds <= 0 or now - last[0] < PROGRESS_EVERY_S:
            return
        last[0] = now
        _stage(db, job, "transcribing", min(end / seconds, 0.99))

    try:
        segments = transcribe.run(wav, on_progress)
    finally:
        wav.unlink(missing_ok=True)  # bản 16 kHz chỉ là tệp tạm, không giữ thêm một bản ghi âm

    # Che PII ngay sau khi chép lời, trước khi bất cứ thứ gì chạm tới LLM hay DB.
    _stage(db, job, "masking", 0.0)
    chunks = _chunks(segments, settings.audio_chunk_minutes)
    mapping: dict[str, str] = {}  # dùng chung: placeholder giống nhau giữa các đoạn
    for c in chunks:
        c["masked"] = mask(c["text"], mapping=mapping).text
    masked = "\n".join(c["masked"] for c in chunks)
    (service.UPLOAD_DIR / f"{row.sha256}.raw.txt").write_text(
        "\n".join(c["text"] for c in chunks), encoding="utf-8"
    )
    service.text_path(row.sha256).write_text(masked, encoding="utf-8")

    doc_id = make_doc_id(row.sha256)
    ingest_text = "\n\n".join(f"{_heading(c)}\n{c['masked']}" for c in chunks) or masked
    res = ingest_upload(
        db, doc_id=doc_id, title=Path(row.filename).stem, text=ingest_text,
        filename=row.filename,
    )

    _stage(db, job, "extracting", 0.0)
    known = known_docs_from_db(db)
    router = get_router()
    # AU2: mặc định chỉ mô hình trong máy; bật Dahl thì chỉ gửi bản đã che (assert_masked)
    allow_dahl = service.get_allow_dahl(db, upload_id)
    seq = db.scalar(select(func.max(LegalNode.seq)).where(LegalNode.doc_id == doc_id)) or 0
    n_cases = n_refs = 0
    for done, c in enumerate(chunks, 1):
        for case in extract_cases(router, c["masked"]):
            n_cases += 1
            seq += 1
            node_id = f"{doc_id}-c{n_cases}"
            body = _case_text(case)
            db.add(
                LegalNode(
                    node_id=node_id, doc_id=doc_id, level="case", parent_id=None,
                    heading=f"Ca tư vấn {n_cases} ({_ts(c['start'])})", text=body, seq=seq,
                    text_hash=hashlib.sha256(body.encode("utf-8")).hexdigest()[:16],
                    embedding=embed_one(body),
                )
            )
            n_refs += _link_refs(db, doc_id, node_id, case, known)
        # Bài toán (AU2): gợi ý cho mô hình, luật sư duyệt sau; không vào node luật.
        save_problems(
            db,
            extract_problems(
                router, c["masked"], start_ts=c["start"], end_ts=c["end"],
                allow_dahl=allow_dahl, mapping=mapping,
            ),
            source_kind="audio",
            upload_id=upload_id,
            processed_by="dahl" if allow_dahl else "local",
        )
        _stage(db, job, "extracting", done / len(chunks))
    db.commit()

    row.doc_id = doc_id
    row.chars = len(masked)
    row.parse_mode = res["parse_mode"]
    row.n_nodes = res["n_nodes"] + n_cases
    row.n_refs = res["n_refs"] + n_refs
    row.preview = masked[: service.PREVIEW_CHARS]
    row.status = "pending_review"
    row.error = None
    job.stage = "done"
    job.progress = 1.0
    job.message = None
    db.commit()


def _stage(db: Session, job: UploadJob, stage: str, progress: float | None = None) -> None:
    job.stage = stage
    if progress is not None:
        job.progress = max(0.0, min(float(progress), 1.0))
    db.commit()


def _fail(db: Session, upload_id: str, message: str) -> None:
    try:
        db.rollback()
        row = db.get(UploadedFile, upload_id)
        if row is not None:
            row.status = "failed"
            row.error = message[:500]
        job = db.get(UploadJob, upload_id)
        if job is None:
            job = UploadJob(upload_id=upload_id, kind="audio")
            db.add(job)
        job.stage = "failed"
        job.message = message[:500]
        db.commit()
    except Exception as exc:  # noqa: BLE001 - không còn gì để cứu, chỉ ghi log
        logger.error("Không ghi được trạng thái lỗi cho tệp {}: {}", upload_id, exc)


def _chunks(segments: list[dict], minutes: int) -> list[dict]:
    """Gom đoạn chép lời theo cửa sổ `minutes` phút, mỗi cụm thành một node."""
    span = max(1, minutes) * 60
    out: list[dict] = []
    for seg in segments:
        index = int(seg["start"] // span)
        if not out or out[-1]["index"] != index:
            out.append({"index": index, "start": seg["start"], "end": seg["end"], "text": ""})
        c = out[-1]
        c["end"] = seg["end"]
        line = f"[{_ts(seg['start'])}] {seg['text']}"
        c["text"] = f"{c['text']}\n{line}" if c["text"] else line
    return out


def _heading(chunk: dict) -> str:
    return f"Đoạn {_ts(chunk['start'])}–{_ts(chunk['end'])}"


def _ts(seconds: float) -> str:
    s = max(0, int(seconds))
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _case_text(case: dict) -> str:
    """Bốn trường của một ca tư vấn, bằng tiếng Việt."""
    return "\n".join(
        [
            f"Tình huống: {case['situation']}",
            f"Câu hỏi: {case['question']}",
            f"Trả lời: {case['answer']}",
            f"Căn cứ: {'; '.join(case['articles'])}",
        ]
    )


def _link_refs(
    db: Session, doc_id: str, from_id: str, case: dict, known: dict[str, str]
) -> int:
    """Nối ca tư vấn tới các node luật đã có (chỉ node có thật trong kho)."""
    pairs: dict[str, str] = {}
    for piece in [*case["articles"], case["answer"]]:
        for to_id, ref_text in extract_refs(piece, doc_id, known_docs=known):
            if to_id != from_id:
                pairs.setdefault(to_id, ref_text)
    if not pairs:
        return 0
    existing = {
        r[0]
        for r in db.execute(
            sql_text("SELECT node_id FROM legal_node WHERE node_id = ANY(:ids)"),
            {"ids": list(pairs)},
        )
    }
    n = 0
    for to_id, ref_text in pairs.items():
        if to_id in existing:
            db.add(NodeReference(from_id=from_id, to_id=to_id, ref_text=ref_text))
            n += 1
    return n
