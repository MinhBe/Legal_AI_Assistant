"""I2 — máy tính lao động theo phiên bản luật tại ngày sự kiện."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.calc.labor import (
    WARNING,
    job_loss,
    limitation,
    notice_days,
    service_years,
    severance,
    unlawful_dismissal,
    version_at,
)
from app.main import app

D2012 = date(2020, 12, 31)
D2019 = date(2021, 1, 1)


@pytest.mark.parametrize(
    ("event_date", "expected"),
    [(D2012, "blld2012"), (D2019, "blld2019")],
)
def test_version_switch(event_date, expected):
    assert version_at(event_date) == expected
    assert severance(10_000_000, 3, event_date=event_date)["version"] == expected


@pytest.mark.parametrize(
    ("event_date", "contract_type", "employer", "term", "expected", "unit"),
    [
        # 2019: người sử dụng lao động — Điều 36 k2
        (D2019, "indefinite", True, None, 45, "ngày"),
        (D2019, "fixed", True, 11, 3, "ngày làm việc"),
        (D2019, "fixed", True, 12, 30, "ngày"),
        (D2019, "fixed", True, 36, 30, "ngày"),
        # 2019: người lao động — Điều 35 k1
        (D2019, "indefinite", False, None, 45, "ngày"),
        (D2019, "fixed", False, 11, 3, "ngày làm việc"),
        (D2019, "fixed", False, 12, 30, "ngày"),
        (D2019, "fixed", False, 36, 30, "ngày"),
        # 2012: người sử dụng lao động — Điều 38 k2
        (D2012, "indefinite", True, None, 45, "ngày"),
        (D2012, "fixed", True, 11, 3, "ngày làm việc"),
        (D2012, "fixed", True, 12, 30, "ngày"),
        (D2012, "fixed", True, 36, 30, "ngày"),
        # 2012: người lao động — Điều 37, mọi hợp đồng xác định thời hạn 3 ngày
        (D2012, "indefinite", False, None, 45, "ngày"),
        (D2012, "fixed", False, 11, 3, "ngày làm việc"),
        (D2012, "fixed", False, 36, 3, "ngày làm việc"),
    ],
)
def test_notice_days(event_date, contract_type, employer, term, expected, unit):
    result = notice_days(contract_type, employer, event_date, term)
    assert result["value"] == expected
    assert result["unit"] == unit
    assert result["version"] == ("blld2019" if event_date >= D2019 else "blld2012")
    assert result["basis"]
    assert WARNING in result["note"]


def test_notice_2012_employee_reason_note_and_2019_basis():
    old = notice_days("fixed", False, D2012, 24)
    assert "Điều 37" in old["note"]
    new = notice_days("fixed", False, D2019, 24)
    assert new["basis"][0]["doc_id"] == "blld2019"
    assert "Điều 35" in new["basis"][0]["label"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"contract_type": "foo", "employer_side": True, "event_date": D2019},
        {"contract_type": "fixed", "employer_side": True, "event_date": D2019},
        {"contract_type": "fixed", "employer_side": True, "event_date": D2019, "term_months": 0},
        {"contract_type": "fixed", "employer_side": True, "event_date": D2019, "term_months": 37},
        {"contract_type": "indefinite", "employer_side": "true", "event_date": D2019},
        {"contract_type": "indefinite", "employer_side": True, "event_date": "2020-13-01"},
    ],
)
def test_notice_invalid(kwargs):
    with pytest.raises(ValueError):
        notice_days(**kwargs)


@pytest.mark.parametrize(
    ("start", "end", "insured", "expected"),
    [
        (date(2020, 1, 1), date(2022, 6, 1), 0, 2.5),   # 29 tháng = 2 năm 5 tháng
        (date(2020, 1, 1), date(2022, 7, 1), 0, 3.0),   # 30 tháng = 2 năm 6 tháng
        (date(2020, 1, 1), date(2020, 6, 1), 0, 0.5),   # 5 tháng
        (date(2020, 1, 1), date(2020, 7, 1), 0, 1.0),   # 6 tháng
        (date(2020, 1, 1), date(2022, 7, 1), 6, 2.0),   # trừ BHTN
    ],
)
def test_service_years_rounding(start, end, insured, expected):
    result = service_years(start, end, insured, event_date=D2019)
    assert result["value"] == pytest.approx(expected)
    assert result["unit"] == "năm"


def test_service_years_versions_and_invalid():
    old = service_years(date(2019, 1, 1), date(2020, 1, 1), event_date=D2012)
    assert old["version"] == "blld2012"
    assert "NĐ 05/2015" in old["note"]
    new = service_years(date(2020, 1, 1), date(2021, 1, 1), event_date=D2019)
    assert new["version"] == "blld2019"
    assert new["basis"][0]["doc_id"] == "nd145_2020"

    with pytest.raises(ValueError):
        service_years(date(2021, 1, 1), date(2020, 1, 1))
    with pytest.raises(ValueError):
        service_years(date(2020, 1, 1), date(2021, 1, 1), 13)


def test_severance_and_basis_by_version():
    old = severance(10_000_000, 3.5, event_date=D2012)
    assert old["value"] == 17_500_000
    assert old["unit"] == "đồng"
    assert old["basis"][0]["doc_id"] == "blld2012"
    new = severance(10_000_000, 3.5, event_date=D2019)
    assert new["value"] == 17_500_000
    assert new["basis"][0]["doc_id"] == "blld2019"
    assert WARNING in new["note"]
    for bad in (-1, "abc", True):
        with pytest.raises(ValueError):
            severance(bad, 3)


def test_job_loss_minimum_two_months():
    assert job_loss(10_000_000, 1, event_date=D2019)["value"] == 20_000_000
    assert job_loss(10_000_000, 3, event_date=D2019)["value"] == 30_000_000
    assert job_loss(10_000_000, 0, event_date=D2019)["value"] == 20_000_000
    assert job_loss(10_000_000, 2, event_date=D2012)["basis"][0]["doc_id"] == "blld2012"
    with pytest.raises(ValueError):
        job_loss(-1, 2)


def test_unlawful_dismissal_components_and_versions():
    # 10 ngày không được làm việc + 2 tháng lương + 5 ngày thiếu báo trước
    result = unlawful_dismissal(
        10_000_000,
        10,
        5,
        daily_salary=400_000,
        event_date=D2019,
    )
    assert result["value"] == 4_000_000 + 20_000_000 + 2_000_000
    assert "bảo hiểm" in result["note"]
    assert result["basis"][0]["doc_id"] == "blld2019"

    default_day = unlawful_dismissal(10_000_000, 10, event_date=D2019)
    assert default_day["value"] == 23_846_154  # 10 × 10tr/26 + 20tr, làm tròn đồng
    assert "giả định" in default_day["note"]

    old = unlawful_dismissal(10_000_000, 0, event_date=D2012)
    assert old["basis"][0]["doc_id"] == "blld2012"
    with pytest.raises(ValueError):
        unlawful_dismissal(10_000_000, -1)


def test_limitation_deadline_and_days_left():
    result = limitation(date(2025, 1, 1), event_date=D2019)
    assert result["deadline"] == "2026-01-01"
    assert result["days_left"] == (date(2026, 1, 1) - date.today()).days
    assert result["value"] == result["days_left"]
    assert result["basis"][0]["doc_id"] == "blld2019"
    assert result["version"] == "blld2019"

    old = limitation(date(2020, 2, 29), event_date=D2012)
    assert old["deadline"] == "2021-02-28"
    assert old["version"] == "blld2012"
    assert old["basis"][0]["doc_id"] == "blld2012"

    with pytest.raises(ValueError):
        limitation(date(2025, 1, 1), dispute="collective")


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.db
def test_calc_api_returns_result_with_basis_and_timeframe(db, client):
    payload = {"avg_salary_6m": 10_000_000, "years": 3, "event_date": "2020-12-31"}
    r = client.post("/api/calc/severance", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "blld2012"
    assert body["value"] == 15_000_000
    assert body["basis"]
    assert all({"doc_id", "label"} <= set(item) for item in body["basis"])
    assert body["timeframe_version"]
    assert all({"doc_id", "title", "number"} <= set(item) for item in body["timeframe_version"])

    r = client.post("/api/calc/severance", json={**payload, "event_date": "2021-01-01"})
    assert r.status_code == 200
    assert r.json()["version"] == "blld2019"


@pytest.mark.db
def test_calc_api_basis_node_id_only_when_present(db, client):
    r = client.post(
        "/api/calc/notice",
        json={
            "contract_type": "indefinite",
            "employer_side": True,
            "event_date": "2021-01-01",
        },
    )
    assert r.status_code == 200, r.text
    item = r.json()["basis"][0]
    assert item["node_id"] == "blld2019-d36-k2"


@pytest.mark.db
@pytest.mark.parametrize(
    ("kind", "payload"),
    [
        ("notice", {"contract_type": "foo", "employer_side": True}),
        ("notice", {"contract_type": "fixed", "employer_side": True}),
        ("service-years", {"start": "2022-01-01", "end": "2021-01-01"}),
        ("severance", {"avg_salary_6m": -1, "years": 1}),
        ("job-loss", {"avg_salary_6m": 1, "years": -1}),
        ("unlawful-dismissal", {"monthly_salary": 1, "days_not_working": -1}),
        ("limitation", {"discovered_on": "2025-01-01", "dispute": "collective"}),
        ("severance", {"avg_salary_6m": 1, "years": 1, "event_date": "2020-13-01"}),
    ],
)
def test_calc_api_422(db, client, kind, payload):
    r = client.post(f"/api/calc/{kind}", json=payload)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]


@pytest.mark.db
def test_calc_api_unknown_kind(db, client):
    r = client.post("/api/calc/unknown", json={})
    assert r.status_code == 404
