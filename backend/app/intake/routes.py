"""API voice intake: chép lời tức thì, chép lời tệp, phát hiện / áp làm mờ, lưu khi có đồng ý.

Xem docs/design/voice-intake.md. Bản thô chỉ đi qua bộ nhớ và trả lại cho chính người gửi;
chỉ bản đã áp lựa chọn làm mờ được lưu, và chỉ khi khách đồng ý xử lý vụ việc.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from loguru import logger
from sqlalchemy.orm import Session

from app.auth import deps as auth
from app.config import get_settings
from app.db.base import get_db
from app.db.models import IntakeRecord
from app.intake import redact

router = APIRouter()
CHAT = [Depends(auth.require("chat"))]
POOL = Path("data/intake/train_pool.jsonl")
MAX_TEXT = 200_000


def _text(body: dict) -> str:
    text = str(body.get("text") or "")
    if not text.strip():
        raise HTTPException(400, "Thiếu nội dung")
    if len(text) > MAX_TEXT:
        raise HTTPException(413, "Nội dung quá dài")
    return text


@router.post("/api/intake/detect", dependencies=CHAT)
def intake_detect(body: dict = Body(...)) -> dict:
    """Các đoạn nhạy cảm để người dùng duyệt. Chỉ luật trong máy, không gọi mô hình."""
    return {"spans": redact.detect(_text(body))}


@router.post("/api/intake/apply", dependencies=CHAT)
def intake_apply(body: dict = Body(...)) -> dict:
    text = _text(body)
    try:
        return redact.apply(text, redact.detect(text), body.get("decisions") or {})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/intake/submit")
def intake_submit(background: BackgroundTasks, body: dict = Body(...),
                  db: Session = Depends(get_db),
                  user: dict = Depends(auth.require("chat"))) -> dict:
    """Lưu bản đã làm mờ, chỉ khi khách tick đồng ý xử lý vụ việc. Đồng ý góp dữ liệu train chỉ
    có hiệu lực với bản không còn đoạn nhạy cảm nào được giữ nguyên."""
    text = _text(body)
    if not body.get("consent_case"):
        raise HTTPException(400, "Cần đồng ý cho dùng nội dung để xử lý vụ việc thì mới lưu")
    try:
        res = redact.apply(text, redact.detect(text), body.get("decisions") or {})
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    kept = res["kept"]
    training = bool(body.get("consent_training")) and kept == 0
    row = IntakeRecord(
        id=uuid.uuid4().hex[:16], username=user.get("username"), client_id=user.get("client_id"),
        source=str(body.get("source") or "text")[:16], text=res["text"], kept_spans=kept,
        span_counts=json.dumps(res["counts"], ensure_ascii=False), consent_case=True,
        consent_training=training, data_class="B" if kept else "C",
    )
    db.add(row)
    db.commit()
    if training:
        POOL.parent.mkdir(parents=True, exist_ok=True)
        with POOL.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"intake_id": row.id, "text": res["text"], "source": row.source},
                               ensure_ascii=False) + "\n")
    if body.get("analyze", True):
        from app.intake import analyze

        background.add_task(analyze.run, row.id)
    return {"intake_id": row.id, "text": res["text"], "data_class": row.data_class,
            "consent_training": training, "kept": kept}


@router.post("/api/stt/file", dependencies=CHAT)
async def stt_file(file: UploadFile = File(...)) -> dict:
    """Chép lời một tệp ghi âm/ghi hình và trả lại ngay cho người tải. Không lưu tệp hay chữ."""
    from app.audio import convert, transcribe

    settings = get_settings()
    data = await file.read()
    if len(data) > settings.audio_max_bytes:
        raise HTTPException(413, "Tệp quá lớn")
    suffix = Path(file.filename or "x.bin").suffix.lower()[:8] or ".bin"
    with tempfile.TemporaryDirectory(prefix="stt_") as tmp:
        src = Path(tmp) / f"in{suffix}"
        src.write_bytes(data)
        try:
            wav = await asyncio.to_thread(convert.to_wav, src)
        except Exception as exc:
            raise HTTPException(400, f"Không đọc được tệp âm thanh: {exc}") from exc
        dur = convert.duration(wav) or 0
        if dur > settings.stt_file_max_s:
            raise HTTPException(413, f"Tệp dài {dur / 60:.0f} phút: hãy gửi qua mục Tải lên để "
                                     "chép lời nền")
        segs = await asyncio.to_thread(transcribe.run, wav)
    return {"duration_s": dur, "segments": segs,
            "text": " ".join(s["text"] for s in segs if s["text"])}


@router.get("/api/intake/{intake_id}")
def intake_get(intake_id: str, db: Session = Depends(get_db),
               user: dict = Depends(auth.require("chat"))) -> dict:
    """Hồ sơ và kết quả phân tích v2.1: chỉ người gửi (tài khoản hoặc mã trình duyệt) xem được."""
    from app.intake import analyze

    row = db.get(IntakeRecord, intake_id)
    owner = row is not None and (
        (row.username and row.username == user.get("username"))
        or (not row.username and row.client_id == user.get("client_id")))
    if not owner:
        raise HTTPException(404, "Không thấy hồ sơ")
    return {"intake_id": row.id, "status": row.status, "data_class": row.data_class,
            "text": row.text, "created_at": row.created_at.isoformat() if row.created_at else None,
            "analysis": analyze.load(row.id)}


def _ws_allowed(ws: WebSocket) -> bool:
    """Trình duyệt không gắn được header vào WebSocket: token đi qua ?token=."""
    from app.auth import roles, tokens

    settings = get_settings()
    if not settings.auth_required:
        return True
    data = tokens.verify(ws.query_params.get("token", ""))
    role = data["role"] if data else "anonymous"
    return "chat" in roles.perms(role)


@router.websocket("/api/stt/live")
async def stt_live(ws: WebSocket) -> None:
    """PCM int16 16 kHz mono (nhị phân) vào; JSON partial/final ra. Tin "stop" để chốt."""
    from app.intake.stt import LIVE_LOCK, LiveSession

    await ws.accept()
    if not _ws_allowed(ws):
        await ws.send_json({"type": "error", "text": "Cần đăng nhập"})
        await ws.close(code=4401)
        return
    if not LIVE_LOCK.acquire(blocking=False):
        await ws.send_json({"type": "error", "text": "Đang có phiên chép lời khác, thử lại sau"})
        await ws.close()
        return
    sess = LiveSession()
    pending = bytearray()
    state = {"stop": False, "gone": False}
    wake = asyncio.Event()

    async def receive() -> None:
        # nhận liên tục, kể cả khi đang chép: socket không bị nghẽn, ping vẫn được trả lời
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                state["gone"] = True
            elif msg.get("bytes"):
                pending.extend(msg["bytes"])
            elif msg.get("text") == "stop":
                state["stop"] = True
            wake.set()
            if state["gone"] or state["stop"]:
                return

    recv = asyncio.create_task(receive())
    try:
        while True:
            await wake.wait()
            wake.clear()
            if pending:  # gộp mọi khối đã tới: CPU chậm thì xử lý một lượt lớn thay vì xếp hàng
                chunk = bytes(pending)
                del pending[:]
                for ev in await asyncio.to_thread(sess.feed, chunk):
                    await ws.send_json(ev)
            if state["gone"]:
                break
            if state["stop"] and not pending:
                for ev in await asyncio.to_thread(sess.close):
                    await ws.send_json(ev)
                await ws.send_json({"type": "done"})
                break
            if pending:
                wake.set()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("stt live lỗi: {}", exc)
        await ws.send_json({"type": "error", "text": "Lỗi chép lời"})
    finally:
        recv.cancel()
        LIVE_LOCK.release()
        try:
            await ws.close()
        except RuntimeError:
            pass
