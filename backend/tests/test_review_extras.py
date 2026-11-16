"""R3 + R4 + R7 — ca bẫy, mức tự chủ theo loại ca, hạn duyệt và lịch trực
(design §9.4, §15.1, §15.5, §15.6)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

pytestmark = pytest.mark.db

Q = "Công ty sa thải tôi có đúng luật?"
DRAFT = "Theo Điều 36 BLLĐ 2019, người sử dụng lao động phải báo trước 45 ngày."
TF = {
    "event_date": "2024-01-01", "event_date_source": "câu hỏi",
    "advice_date": "2024-06-01", "as_of": "2024-01-01",
    "applicable": [], "changes_after": [], "upcoming": [],
    "transition_rules": [], "flags": [],
}
VERIFIER = {"ok": True, "checked": 2, "problems": [], "dropped": []}
REASONS = [{"code": "high_stakes", "weight": 3, "message": "câu hỏi về sa thải"}]


@pytest.fixture(scope="module", autouse=True)
def _tables():
    """`create_all` tạo bảng mới (autonomy_level, duty_status) nếu chưa có."""
    from app.db import models  # noqa: F401
    from app.db.base import Base, engine

    try:
        Base.metadata.create_all(bind=engine)
    except Exception as exc:  # noqa: BLE001 - mọi lỗi kết nối đều là "không có DB"
        pytest.skip(f"không kết nối được Postgres: {exc.__class__.__name__}")


@pytest.fixture(autouse=True)
def _restore():
    """Trả DB về đúng trạng thái trước test: xoá dòng mới, phục hồi mức tự chủ + lịch trực."""
    from app.db.base import SessionLocal
    from app.db.models import AnswerRecord, AutonomyLevel, DutyStatus, ReviewCase

    try:
        db = SessionLocal()
        before = {
            "cases": set(db.scalars(select(ReviewCase.id)).all()),
            "records": set(db.scalars(select(AnswerRecord.id)).all()),
            "levels": {r.case_type: (r.level, r.reason)
                       for r in db.scalars(select(AutonomyLevel))},
            "duty": {r.id: (r.on_duty, r.lawyer, r.backup)
                     for r in db.scalars(select(DutyStatus))},
        }
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"không kết nối được Postgres: {exc.__class__.__name__}")
    db.close()
    yield
    db = SessionLocal()
    for case_id in set(db.scalars(select(ReviewCase.id)).all()) - before["cases"]:
        db.execute(text("DELETE FROM review_case WHERE id = :id"), {"id": case_id})
    for rec_id in set(db.scalars(select(AnswerRecord.id)).all()) - before["records"]:
        db.execute(text("DELETE FROM answer_record WHERE id = :id"), {"id": rec_id})
    for row in list(db.scalars(select(AutonomyLevel))):
        if row.case_type in before["levels"]:
            row.level, row.reason = before["levels"][row.case_type]
        else:
            db.delete(row)
    for row in list(db.scalars(select(DutyStatus))):
        if row.id in before["duty"]:
            row.on_duty, row.lawyer, row.backup = before["duty"][row.id]
        else:
            db.delete(row)
    db.commit()
    db.close()


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi import FastAPI

    from app.api import routes

    monkeypatch.setattr(routes, "_ESC_FILE", tmp_path / "escalations.json")
    monkeypatch.setattr(routes, "_esc_imported", True)
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def _mk_case(ct: str = "cham_dut", created_at: datetime | None = None) -> str:
    from app.db.base import SessionLocal
    from app.db.models import AnswerRecord, ReviewCase

    db = SessionLocal()
    try:
        rec_id = uuid.uuid4().hex[:12]
        db.add(AnswerRecord(
            id=rec_id, thread_id="t-r347", data_class="C", question=Q, answer=DRAFT,
            advice_date=datetime(2024, 6, 1).date(), event_date=None,
            as_of=datetime(2024, 1, 1).date(),
            provisions=json.dumps([]), timeframe=json.dumps(TF),
            verifier=json.dumps(VERIFIER), corpus_snapshot="{}", prompt_version="qa-v1",
            provider="dahl", model="dahl-7b", category="legal",
        ))
        case_id = uuid.uuid4().hex[:16]
        extra = {"created_at": created_at} if created_at else {}
        db.add(ReviewCase(
            id=case_id, answer_id=rec_id, question=Q, risk_score="5",
            reasons=json.dumps(REASONS, ensure_ascii=False), status="pending",
            source="auto", thread_id="t-r347", case_type=ct, **extra,
        ))
        db.commit()
        return case_id
    finally:
        db.close()


def _fake_chat(message, history, mode):
    yield ("step", {"name": "retrieve", "label": "Đang tra cứu văn bản"})
    yield ("token", {"text": "Công ty sa thải bạn phải báo trước 45 ngày theo Điều 36."})
    yield ("citation", {"n": 1, "node_id": "blld2019-d36", "display": "Điều 36", "text": "..."})
    yield ("verifier", VERIFIER)
    yield ("timeframe", TF)
    yield ("done", {"category": "legal", "confidence": 0.9})


def _risk(body: str) -> dict:
    assert "event: risk" in body, body[-600:]
    return json.loads(body.split("event: risk", 1)[1].split("data: ", 1)[1].split("\n", 1)[0])


def _levels(client) -> dict:
    return {row["case_type"]: row for row in client.get("/api/review/autonomy").json()}


# ---- 1. loại ca theo từ khoá ----
@pytest.mark.parametrize(("question", "expected"), [
    ("Công ty sa thải tôi có đúng luật?", "cham_dut"),
    ("Lương làm thêm giờ tính thế nào?", "tien_luong"),
    ("Tôi được nghỉ phép mấy ngày?", "nghi_ngoi"),
    ("Kỷ luật lao động khiển trách có đúng không?", "ky_luat"),
    ("Hợp đồng thử việc tối đa bao lâu?", "hop_dong"),
    ("Công đoàn có quyền gì?", "khac"),
])
def test_case_type_by_keywords(question, expected):
    from app.review.autonomy import case_type

    assert case_type(question) == expected


# ---- 2. mức tự chủ: mặc định 0, PATCH, tụt 0 khi lỗi nghiêm trọng ----
def test_autonomy_patch_drop_and_unconfirmed_chat(client, monkeypatch):
    from app.api import routes

    assert _levels(client)["cham_dut"]["level"] == 0  # thiếu dòng = mức 0

    r = client.patch("/api/review/autonomy/cham_dut",
                     json={"level": 1, "reason": "đủ 60 ca sạch"})
    assert r.status_code == 200, r.text
    assert r.json()["level"] == 1 and r.json()["reason"] == "đủ 60 ca sạch"
    assert client.patch("/api/review/autonomy/cham_dut", json={"level": 4}).status_code == 422

    # mức 1 + ca vào hàng đợi -> câu trả lời mang nhãn "chưa xác nhận"
    monkeypatch.setattr(routes, "run_chat", _fake_chat)
    payload = _risk(client.post("/api/chat", json={"message": Q}).text)
    assert payload["queue"] is True
    assert (payload["case_type"], payload["autonomy_level"]) == ("cham_dut", 1)
    assert payload["unconfirmed"] is True

    # sửa nhiều kèm lỗi nghiêm trọng -> loại ca tụt về 0
    case_id = payload["case_id"]
    r = client.post(f"/api/review/cases/{case_id}/act", json={
        "action": "heavy_edit", "text": "Bản mới", "labels": ["sai_trich_dan"],
        "reason": "trích sai điều",
    })
    assert r.status_code == 200, r.text
    row = _levels(client)["cham_dut"]
    assert row["level"] == 0
    assert "Tụt về 0 do lỗi nghiêm trọng (sai_trich_dan)" in row["reason"]
    assert case_id in row["reason"]


# ---- 3. ca bẫy: 1/20 ca, tỷ lệ bắt ----
def _mk_auto(n: int) -> list[str]:
    """Chèn n ca tự động, gọi `maybe_insert_trap` sau mỗi ca như luồng chat."""
    from app.db.base import SessionLocal
    from app.db.models import ReviewCase
    from app.review import traps

    ids: list[str] = []
    db = SessionLocal()
    try:
        for _ in range(n):
            case_id = uuid.uuid4().hex[:16]
            db.add(ReviewCase(id=case_id, question=Q, risk_score="5", reasons="[]",
                              status="pending", source="auto"))
            db.commit()
            ids.append(case_id)
            trap_id = traps.maybe_insert_trap(db)
            if trap_id:
                ids.append(trap_id)
    finally:
        db.close()
    return ids


def test_traps_one_per_twenty_and_catch_rate(client):
    from app.db.base import SessionLocal
    from app.db.models import ReviewCase
    from app.review import service as review

    before = client.get("/api/review/stats").json()["traps"]

    ids = _mk_auto(20)  # 20 ca liên tiếp luôn vắt qua đúng một bội số của 20
    assert client.get("/api/review/stats").json()["traps"]["total"] == before["total"] + 1
    ids += _mk_auto(20)
    assert client.get("/api/review/stats").json()["traps"]["total"] == before["total"] + 2

    db = SessionLocal()
    try:
        trap_ids = list(db.scalars(select(ReviewCase.id).where(
            ReviewCase.id.in_(ids), ReviewCase.source == "trap")))
        assert len(trap_ids) == 2
        approve_id, reject_id = trap_ids
        pkg = review.package(db, approve_id)
        # bản nháp cài lỗi đọc được như ca thường; câu hỏi không lộ dấu ca kiểm tra
        assert pkg["draft"] and "(ca kiểm tra)" not in pkg["question"]
        assert "(ca kiểm tra)" not in str(pkg["reasons"])  # chưa duyệt: không lộ là ca bẫy
        assert pkg["reviewer_text"] == pkg["draft"]
    finally:
        db.close()

    assert client.post(f"/api/review/cases/{approve_id}/act",
                       json={"action": "approve"}).status_code == 200
    assert client.post(f"/api/review/cases/{reject_id}/act", json={
        "action": "reject", "reason": "Sai phiên bản luật", "labels": ["sai_phien_ban"],
    }).status_code == 200

    got = client.get("/api/review/stats").json()["traps"]
    assert got["total"] == before["total"] + 2
    assert got["reviewed"] == before["reviewed"] + 2
    assert got["caught"] == before["caught"] + 1
    assert got["catch_rate"] == round((before["caught"] + 1) / (before["reviewed"] + 2), 4)


# ---- 4. hạn duyệt: +1 ngày làm việc, +4 giờ khi gần thời hiệu ----
def test_due_at_skips_weekend_and_near_limitation_is_four_hours(client):
    from app.review.sla import due_at, overdue

    friday = datetime(2025, 5, 2, 10, 0, tzinfo=UTC)  # Thứ Sáu
    case = SimpleNamespace(created_at=friday, reasons="[]", status="pending")
    assert due_at(case) == datetime(2025, 5, 5, 10, 0, tzinfo=UTC)  # Thứ Hai
    near = SimpleNamespace(created_at=friday, status="pending",
                           reasons=json.dumps([{"code": "near_limitation"}]))
    assert due_at(near) == friday + timedelta(hours=4)
    assert overdue(case, now=friday) is False
    assert overdue(case, now=datetime(2025, 5, 6, 0, 0, tzinfo=UTC)) is True

    # case_row trả hạn duyệt + cờ quá hạn cho /review
    case_id = _mk_case(created_at=datetime.now(UTC) - timedelta(days=5))
    rows = client.get("/api/review/cases", params={"status": "pending"}).json()
    row = next(r for r in rows if r["id"] == case_id)
    assert row["due_at"] and row["overdue"] is True


# ---- 5. không có luật sư trực: mọi mức về 0, chat gắn cờ no_lawyer ----
def test_no_lawyer_drops_levels_and_flags_chat(client, monkeypatch):
    from app.api import routes

    assert client.patch("/api/review/autonomy/tien_luong",
                        json={"level": 2, "reason": "ổn định"}).status_code == 200
    r = client.patch("/api/review/duty",
                     json={"on_duty": False, "lawyer": "LS A", "backup": "LS B"})
    assert r.status_code == 200, r.text
    duty = r.json()
    assert (duty["on_duty"], duty["lawyer"], duty["backup"]) == (False, "LS A", "LS B")

    rows = client.get("/api/review/autonomy").json()
    assert all(row["level"] == 0 for row in rows), rows
    assert next(x for x in rows if x["case_type"] == "tien_luong")["reason"] == \
        "Không có luật sư trực"

    monkeypatch.setattr(routes, "run_chat", _fake_chat)
    payload = _risk(client.post("/api/chat", json={"message": Q}).text)
    assert payload["queue"] is True and payload["no_lawyer"] is True


def test_pending_trap_looks_like_an_auto_case():
    from app.db.models import ReviewCase
    from app.review.service import case_row

    c = ReviewCase(id="t", question="q", risk_score="3", status="pending", source="trap",
                   reasons='[{"code": "trap", "weight": 3, "message": "(ca kiểm tra) Lỗi cài sẵn"}]',
                   reviewer_text="nháp sai", reply="đáp án đúng")
    row = case_row(c)
    assert row["source"] == "auto" and row["reply"] is None
    assert "ca kiểm tra" not in str(row["reasons"])
    c.status = "rejected"  # sau khi duyệt thì lộ ra để học
    assert case_row(c)["source"] == "trap" and case_row(c)["reply"] == "đáp án đúng"
