"""Rà soát hợp đồng lao động: luật code, không LLM, không DB."""

from __future__ import annotations

from datetime import date

from app.contract import review

BAD = """HỢP ĐỒNG LAO ĐỘNG
Bên A: Công ty TNHH ABC, địa chỉ 12 Lê Lợi, Quận 1.
Bên B: Nguyễn Văn A, ngày sinh 01/01/1995, CCCD số 0790...
Điều 1. Công việc
Vị trí: nhân viên kinh doanh. Địa điểm làm việc: TP. Hồ Chí Minh, vùng I.
Điều 2. Thời hạn hợp đồng
Hợp đồng xác định thời hạn 48 tháng. Thời gian thử việc 3 tháng, lương thử việc bằng 70% lương chính thức.
Điều 3. Tiền lương
Mức lương cơ bản: 4.500.000 đồng/tháng, trả lương bằng chuyển khoản ngày 5 hằng tháng.
Điều 4. Thời giờ làm việc
Làm việc 10 giờ/ngày, 60 giờ/tuần. Làm thêm tối đa 60 giờ/tháng. Nghỉ phép 10 ngày mỗi năm.
Điều 5. Cam kết
Bên B nộp bản chính bằng đại học, công ty giữ bản chính trong thời gian làm việc và đặt cọc 5.000.000 đồng.
Phạt tiền 200.000 đồng mỗi lần đi muộn vi phạm nội quy.
Người lao động muốn nghỉ việc phải báo trước 60 ngày.
"""

GOOD = """HỢP ĐỒNG LAO ĐỘNG
Bên A: Công ty TNHH ABC (người sử dụng lao động), địa chỉ 12 Lê Lợi.
Bên B: người lao động Trần Thị B, ngày sinh 02/02/1996, CCCD số ...
Điều 1. Công việc: chức danh kế toán yêu cầu trình độ đại học, địa điểm làm việc Hà Nội, vùng I.
Điều 2. Hợp đồng không xác định thời hạn. Thử việc 30 ngày, lương thử việc 85%.
Điều 3. Mức lương 12.000.000 đồng, hình thức trả lương chuyển khoản. Xét nâng lương mỗi năm.
Điều 4. Thời giờ làm việc 8 giờ/ngày, 40 giờ/tuần; nghỉ hằng năm 12 ngày.
Điều 5. Trang bị bảo hộ lao động theo quy định. Tham gia bảo hiểm xã hội, bảo hiểm y tế, bảo hiểm thất nghiệp.
Điều 6. Đào tạo, bồi dưỡng theo nhu cầu công việc.
"""


def _rules(res):
    return {f["rule"] for f in res["findings"]}


def test_bad_contract_flags_every_violation():
    res = review.check(BAD, as_of=date(2026, 11, 21))
    expected = {"term_too_long", "probation_too_long", "probation_pay_low", "below_min_wage",
                "hours_day", "hours_week", "overtime_month", "annual_leave_low",
                "hold_documents", "deposit", "fine_instead_of_discipline", "notice_too_long"}
    assert expected <= _rules(res), expected - _rules(res)
    assert res["verdict"] == "risky"
    assert res["findings"][0]["severity"] == "high"


def test_findings_carry_basis_clause_and_quote():
    res = review.check(BAD, as_of=date(2026, 11, 21))
    f = next(x for x in res["findings"] if x["rule"] == "term_too_long")
    assert f["basis"][0]["label"] == "BLLĐ 2019 Điều 20 khoản 1 điểm b"
    assert f["clause"] == 2
    assert "48 tháng" in f["quote"]
    wage = next(x for x in res["findings"] if x["rule"] == "below_min_wage")
    assert "Nghị định 293/2025" in wage["basis"][1]["label"]


def test_min_wage_follows_as_of_date():
    assert review.min_wage_at(date(2025, 6, 1), "I")["amount"] == 4_960_000
    assert review.min_wage_at(date(2026, 1, 1), "I")["amount"] == 5_310_000
    assert review.min_wage_at(date(2024, 1, 1), "I") is None
    # 5.000.000 đ vùng I: hợp lệ năm 2025, dưới mức năm 2026
    text = "Điều 1. Mức lương 5.000.000 đồng, làm việc tại vùng I."
    assert "below_min_wage" not in _rules(review.check(text, as_of=date(2025, 6, 1)))
    assert "below_min_wage" in _rules(review.check(text, as_of=date(2026, 2, 1)))


def test_good_contract_is_clean():
    res = review.check(GOOD, as_of=date(2026, 11, 21))
    assert res["findings"] == [], res["findings"]
    assert res["verdict"] == "ok"
    assert res["facts"]["contract_type"] == "indefinite"


def test_missing_required_content_listed():
    res = review.check("Điều 1. Mức lương 6.000.000 đồng, vùng I.", as_of=date(2026, 11, 21))
    points = {m["point"] for m in res["missing"]}
    assert {"h", "i", "k"} <= points
    assert res["verdict"] == "review"


def test_split_clauses():
    cl = review.split_clauses(BAD)
    assert [c["no"] for c in cl] == [None, 1, 2, 3, 4, 5]
    assert cl[2]["title"] == "Thời hạn hợp đồng"


def test_api_route_without_db():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.contract.routes import router
    from app.db.base import get_db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: None
    r = TestClient(app).post("/api/contract/review", json={"text": BAD, "as_of": "2026-11-21"})
    assert r.status_code == 200
    assert r.json()["verdict"] == "risky"
    assert TestClient(app).post("/api/contract/review", json={"text": "ngắn"}).status_code == 422
