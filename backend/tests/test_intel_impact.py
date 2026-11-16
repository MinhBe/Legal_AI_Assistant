"""LI2b — ảnh hưởng của tin mới: điều luật, máy tính, ca golden, hồ sơ tra cứu, báo động.

Không gọi mạng và không gọi LLM: phân tích ở đây là dict viết tay. Các test cần Postgres
mang @pytest.mark.db và tự bỏ qua khi kho trống; dòng nào test tạo ra thì test xoá lại.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.models import AnswerRecord, IntelImpact, IntelItem, ReviewCase
from app.intel import alerts, impact, store

#: phân tích tối thiểu, đúng schema analyze.Analysis
def _analysis(**over) -> dict:
    base = {
        "relevant_labor": True,
        "topic": "Tiền lương tối thiểu",
        "summary": "Nghị định quy định mức lương tối thiểu vùng.",
        "what_changes": "mức lương tối thiểu vùng tăng",
        "amends": [],
        "replaces": [],
        "affected_nodes": [],
        "effective_date": None,
        "impact": "cao",
        "impact_reason": "Ảnh hưởng trực tiếp tiền lương của mọi người lao động.",
        "routing": {"queue": "tiền lương", "action": "nạp ngay", "kg_updates": []},
        "needs_full_text": False,
        "confidence": 0.7,
        "priority": 2,
    }
    base.update(over)
    return base


def _item(db, created, *, title: str, analysis: dict | None = None) -> IntelItem:
    """Một tin mới, URL riêng cho mỗi lần gọi để chạy lại test không đụng nhau."""
    item = store.add_item(db, {
        "source": "test",
        "url": f"https://li2b.example/{uuid.uuid4().hex}",
        "title": title,
        "number": "999/2026/NĐ-CP",
        "labor_hint": True,
    })
    assert item is not None
    created["item"].append(item.id)
    if analysis is not None:
        item.analysis = json.dumps(analysis, ensure_ascii=False)
        item.status = "analysed"
    db.commit()
    db.refresh(item)
    return item


def _answer(db, created, *, question: str, nodes: list[str]) -> AnswerRecord:
    rec = AnswerRecord(
        id=uuid.uuid4().hex[:16],
        data_class="C",
        question=question,
        answer="(câu trả lời thử)",
        advice_date=date.today(),
        as_of=date(2021, 1, 1),
        provisions=json.dumps([{"node_id": n, "doc_id": n.split("-")[0]} for n in nodes]),
        timeframe="{}",
        corpus_snapshot="{}",
        prompt_version="test",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    created["answer"].append(rec.id)
    return rec


@pytest.fixture
def li2b(db):
    """Bảng ảnh hưởng có sẵn (test không chạy lifespan), và dọn mọi dòng test tạo ra."""
    IntelImpact.__table__.create(bind=db.get_bind(), checkfirst=True)
    created: dict[str, list[str]] = {"item": [], "answer": [], "case": []}
    yield created
    db.rollback()
    for case_id in created["case"]:
        db.execute(delete(ReviewCase).where(ReviewCase.id == case_id))
    for rec_id in created["answer"]:
        db.execute(delete(AnswerRecord).where(AnswerRecord.id == rec_id))
    for item_id in created["item"]:
        db.execute(delete(IntelImpact).where(IntelImpact.item_id == item_id))
        db.execute(delete(IntelItem).where(IntelItem.id == item_id))
    db.commit()


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app) as test_client:  # lifespan: tạo bảng + seed tài khoản
        yield test_client


def _token(client, username: str) -> dict[str, str]:
    resp = client.post("/api/auth/login", json={"username": username, "password": username})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


# ---------- 1. compute ----------
@pytest.mark.db
def test_compute_maps_wages_to_calculators_golden_and_answers(db, li2b):
    item = _item(db, li2b, title="Nghị định quy định mức lương tối thiểu vùng")
    analysis = _analysis(affected_nodes=["blld2019-d90"])
    rec = _answer(
        db, li2b, nodes=["blld2019-d90"],
        question="Mức lương tối thiểu vùng của tôi là bao nhiêu?",
    )

    data = impact.compute(db, item, analysis)

    kinds = {calc["kind"] for calc in data["calculators"]}
    assert {"severance", "job-loss", "unlawful-dismissal"} <= kinds
    assert "limitation" not in kinds
    assert all(calc["reason"] for calc in data["calculators"])

    assert [row["node_id"] for row in data["articles"]] == ["blld2019-d90"]
    assert data["articles"][0]["display"].startswith("Điều 90")

    # golden: câu hỏi về tiền lương khớp từ khoá của máy tính
    assert any(row["id"] == "A08" for row in data["golden"])
    # hồ sơ tra cứu đã trích Điều 90, mới nhất trước (kho dev có thể có hồ sơ cũ khớp từ khoá)
    assert data["answers"][0]["id"] == rec.id
    assert data["answers"][0]["question"].startswith("Mức lương tối thiểu")
    assert len(data["answers"]) <= impact.MAX_ANSWERS
    assert data["summary"].startswith("Ảnh hưởng: 1 điều luật")
    assert store.get_impact(db, item.id) is not None  # đã lưu

    # golden: ca trích đúng Điều bị ảnh hưởng, dù tiêu đề không có từ khoá máy tính
    other = _item(db, li2b, title="Thông tư về hồ sơ quản lý lao động")
    cited = impact.compute(db, other, _analysis(topic="Hồ sơ", what_changes="chưa rõ",
                                               affected_nodes=["blld2019-d46"], impact="thấp"))
    assert cited["calculators"] == []
    assert any(row["id"] == "A03" for row in cited["golden"])  # A03 trích blld2019-d46


@pytest.mark.db
def test_compute_adds_articles_of_amended_documents(db, li2b):
    item = _item(db, li2b, title="Nghị định sửa đổi Nghị định 145/2020/NĐ-CP")
    data = impact.compute(db, item, _analysis(amends=["145/2020/NĐ-CP"], topic="Hợp đồng"))

    node_ids = [row["node_id"] for row in data["articles"]]
    assert "nd145_2020-d8" in node_ids  # Điều của văn bản bị sửa đổi
    assert all(node_id.startswith("nd145_2020-d") for node_id in node_ids)
    assert len(node_ids) <= impact.MAX_ARTICLES
    assert any(row["id"] == "B02" for row in data["golden"])  # B02 trích nd145_2020-d8


# ---------- 2. cảnh báo ở máy tính ----------
@pytest.mark.db
def test_calc_warning_appears_until_the_item_is_approved(db, li2b, monkeypatch, client):
    from app.auth import deps

    monkeypatch.setattr(deps.settings, "auth_required", True)
    analysis = _analysis(impact="cao")
    item = _item(db, li2b, title="Nghị định quy định mức lương tối thiểu vùng", analysis=analysis)
    impact.compute(db, item, analysis)

    payload = {"avg_salary_6m": 10_000_000, "years": 3}
    before = client.post("/api/calc/severance", json=payload)
    assert before.status_code == 200, before.text
    warnings = before.json()["warnings"]
    assert any(item.title in w and "chờ luật sư duyệt" in w for w in warnings)
    # máy tính không liên quan thì không bị cảnh báo
    assert "warnings" not in client.post(
        "/api/calc/notice",
        json={"contract_type": "indefinite", "employer_side": True},
    ).json()

    admin = _token(client, "admin")
    approved = client.post(f"/api/intel/items/{item.id}/approve", headers=admin)
    assert approved.status_code == 200, approved.text

    after = client.post("/api/calc/severance", json=payload)
    assert not any(item.title in w for w in after.json().get("warnings", []))


# ---------- 3. báo động cho luật sư ----------
@pytest.mark.db
def test_raise_for_creates_exactly_one_case_for_high_impact(db, li2b):
    analysis = _analysis(impact="cao", priority=1)
    item = _item(db, li2b, title="Nghị định sửa đổi quy định về tiền lương", analysis=analysis)
    data = impact.compute(db, item, analysis)

    case_id = alerts.raise_for(db, item, analysis, data)
    assert case_id
    li2b["case"].append(case_id)
    assert alerts.raise_for(db, item, analysis, data) == case_id  # gọi lại: vẫn một ca

    cases = db.scalars(
        select(ReviewCase).where(ReviewCase.source == "intel", ReviewCase.question == item.title)
    ).all()
    assert len(cases) == 1
    assert cases[0].status == "pending"
    assert cases[0].case_type == "intel" and cases[0].risk_score == "intel"
    reasons = json.loads(cases[0].reasons)
    assert reasons[0]["code"] == "intel" and reasons[0]["message"] == analysis["impact_reason"]
    assert any(row["message"] == data["summary"] for row in reasons[1:])


@pytest.mark.db
def test_raise_for_skips_low_impact_unless_watchlist_priority_3(db, li2b):
    low = _analysis(impact="thấp", priority=1)
    item = _item(db, li2b, title="Quyết định về quản lý giá đất trên địa bàn tỉnh", analysis=low)
    data = impact.compute(db, item, low)
    assert alerts.raise_for(db, item, low, data) is None
    assert not db.scalars(select(ReviewCase).where(ReviewCase.question == item.title)).all()

    watched = _analysis(impact="thấp", priority=3)
    other = _item(db, li2b, title="Nghị định sửa đổi Nghị định 145/2020/NĐ-CP", analysis=watched)
    case_id = alerts.raise_for(db, other, watched, impact.compute(db, other, watched))
    assert case_id
    li2b["case"].append(case_id)


# ---------- 4. API bản tin + báo động ----------
@pytest.mark.db
def test_digest_groups_by_day_and_alerts_list_only_high(db, li2b, monkeypatch, client):
    from app.auth import deps

    monkeypatch.setattr(deps.settings, "auth_required", True)
    high = _analysis(impact="cao", priority=2)
    item_high = _item(db, li2b, title="Nghị định quy định mức lương tối thiểu vùng", analysis=high)
    impact.compute(db, item_high, high)
    low = _analysis(impact="thấp", priority=0, topic="Đất đai", what_changes="chưa rõ")
    item_low = _item(db, li2b, title="Quyết định về quản lý giá đất", analysis=low)
    impact.compute(db, item_low, low)

    admin = _token(client, "admin")
    normal = _token(client, "user1")
    assert client.get("/api/intel/alerts", headers=normal).status_code == 403
    assert client.get("/api/intel/digest", headers=normal).status_code == 403

    body = client.get("/api/intel/alerts", headers=admin).json()
    listed = [row["id"] for row in body["items"]]
    assert item_high.id in listed
    assert item_low.id not in listed
    assert body["unseen"] == len(listed)
    assert all(row["impact"] == "cao" for row in body["items"])
    assert all(row["created_at"] for row in body["items"])

    digest = client.get("/api/intel/digest?days=7", headers=admin).json()
    days = [block["day"] for block in digest]
    assert days == sorted(days, reverse=True)
    block = next(b for b in digest if any(row["id"] == item_high.id for row in b["items"]))
    ids = [row["id"] for row in block["items"]]
    assert ids.index(item_high.id) < ids.index(item_low.id)  # ảnh hưởng cao trước
    row = next(r for r in block["items"] if r["id"] == item_high.id)
    assert row["impact_summary"].startswith("Ảnh hưởng:")
    assert {"articles", "calculators", "golden", "answers", "case_id"} <= set(row)
