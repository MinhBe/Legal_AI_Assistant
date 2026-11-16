"""Máy tính lao động theo phiên bản luật tại ngày sự kiện (design §8, I2).

Thuần Python + tra `legal_node` khi có session; không gọi LLM. Mọi kết quả đều
mang căn cứ pháp lý và nhãn "Kết quả tính tự động — cần luật sư đối chiếu".
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

WARNING = "Kết quả tính tự động — cần luật sư đối chiếu"

_CUTOVER = date(2021, 1, 1)
_DOC_2012 = "blld2012"
_DOC_2019 = "blld2019"
_DOC_ND145 = "nd145_2020"
_DOC_ND05 = "nd05_2015"

_MONEY = Decimal("1")


def version_at(event_date: date | str | None) -> str:
    """BLLĐ 2012 trước 01/01/2021, BLLĐ 2019 từ ngày đó."""
    day = _as_date(event_date, "event_date") if event_date is not None else date.today()
    return "blld2019" if day >= _CUTOVER else "blld2012"


def _as_date(value: Any, field: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            pass
    raise ValueError(f"{field} không hợp lệ (cần ngày dạng YYYY-MM-DD)")


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} phải là số nguyên không âm")
    return value


def _money(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{field} phải là số không âm")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{field} phải là số không âm") from None
    if not amount.is_finite() or amount < 0:
        raise ValueError(f"{field} phải là số không âm")
    return amount


def _years(value: Any, field: str = "years") -> Decimal:
    amount = _money(value, field)
    return amount


def _term_months(term_months: Any) -> int:
    if term_months is None:
        raise ValueError("hợp đồng xác định thời hạn cần term_months (số tháng)")
    months = _int(term_months, "term_months")
    if not 1 <= months <= 36:
        raise ValueError("term_months phải từ 1 đến 36 tháng")
    return months


def _round_vnd(amount: Decimal) -> int:
    return int(amount.quantize(_MONEY, rounding=ROUND_HALF_UP))


def _num(value: Any) -> str:
    """Số trong bước tính, dấu chấm ngăn cách hàng nghìn."""
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
    else:
        text = str(value)
    head, _, tail = text.partition(".")
    sign = "-" if head.startswith("-") else ""
    digits = head.lstrip("-")
    grouped = f"{int(digits):,}".replace(",", ".")
    return f"{sign}{grouped}" + (f",{tail}" if tail else "")


def _vnd(amount: Decimal) -> str:
    return _num(int(amount))


def _vn_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def _basis(db: Any, doc_id: str, node_id: str | None, label: str) -> dict:
    item: dict = {"doc_id": doc_id, "label": label}
    if db is not None and node_id:
        from app.db.models import LegalNode

        if db.get(LegalNode, node_id) is not None:
            item["node_id"] = node_id
    return item


def _result(
    version: str,
    value: int | float | str,
    unit: str,
    steps: list[str],
    basis: list[dict],
    note: str = "",
) -> dict:
    notes = [WARNING]
    if note:
        notes.append(note)
    return {
        "value": value,
        "unit": unit,
        "steps": steps,
        "basis": basis,
        "version": version,
        "note": " ".join(notes),
    }


def notice_days(
    contract_type: str,
    employer_side: bool,
    event_date: date | str,
    term_months: int | None = None,
    *,
    db: Any = None,
) -> dict:
    """Thời hạn báo trước khi đơn phương chấm dứt hợp đồng lao động."""
    day = _as_date(event_date, "event_date")
    version = version_at(day)
    if contract_type not in ("indefinite", "fixed"):
        raise ValueError("contract_type phải là 'indefinite' hoặc 'fixed'")
    if not isinstance(employer_side, bool):
        raise ValueError("employer_side phải là true/false")

    note = ""
    if version == "blld2019":
        doc_id, article = _DOC_2019, "BLLĐ 2019"
        if employer_side:
            node, clause = "d36-k2", "Điều 36 khoản 2"
        else:
            node, clause = "d35-k1", "Điều 35 khoản 1"
        if contract_type == "indefinite":
            days, unit = 45, "ngày"
        else:
            months = _term_months(term_months)
            days, unit = (30, "ngày") if months >= 12 else (3, "ngày làm việc")
    else:
        doc_id, article = _DOC_2012, "BLLĐ 2012"
        if employer_side:
            node, clause = "d38-k2", "Điều 38 khoản 2"
            if contract_type == "indefinite":
                days, unit = 45, "ngày"
            else:
                months = _term_months(term_months)
                days, unit = (30, "ngày") if months >= 12 else (3, "ngày làm việc")
        else:
            node, clause = "d37-k1", "Điều 37 khoản 1"
            if contract_type == "indefinite":
                days, unit = 45, "ngày"
            else:
                days, unit = 3, "ngày làm việc"
                note = "Cần đối chiếu lý do theo Điều 37 BLLĐ 2012."

    label = f"{article} {clause}"
    steps = [
        f"Ngày sự kiện {_vn_date(day)} → áp dụng {article}.",
        f"Loại hợp đồng: {'không xác định thời hạn' if contract_type == 'indefinite' else 'xác định thời hạn'}.",
        f"Thời hạn báo trước: {days} {unit} ({label}).",
    ]
    return _result(
        version,
        days,
        unit,
        steps,
        [_basis(db, doc_id, f"{doc_id}-{node}", label)],
        note,
    )


def _full_months(start: date, end: date) -> int:
    """Số tháng tròn đã làm việc giữa hai ngày."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


def service_years(
    start: date | str,
    end: date | str,
    unemployment_insured_months: int = 0,
    *,
    event_date: date | str | None = None,
    db: Any = None,
) -> dict:
    """Thời gian làm việc để tính trợ cấp, trừ thời gian đã đóng BHTN."""
    first = _as_date(start, "start")
    last = _as_date(end, "end")
    if last < first:
        raise ValueError("end phải sau hoặc bằng start")
    insured = _int(unemployment_insured_months, "unemployment_insured_months")
    total = _full_months(first, last)
    if insured > total:
        raise ValueError("unemployment_insured_months không vượt quá tổng thời gian làm việc")

    version = version_at(event_date if event_date is not None else last)
    net = total - insured
    whole = net // 12
    remainder = net % 12
    if remainder >= 6:
        extra = Decimal("1")
        rounding = "+1 năm"
    elif remainder >= 1:
        extra = Decimal("0.5")
        rounding = "+0,5 năm"
    else:
        extra = Decimal("0")
        rounding = "không cộng thêm"
    years = Decimal(whole) + extra

    if version == "blld2019":
        basis = [
            _basis(
                db,
                _DOC_ND145,
                "nd145_2020-d8-k3",
                "NĐ 145/2020 Điều 8 khoản 3",
            )
        ]
        note = ""
    else:
        basis = [_basis(db, _DOC_ND05, None, "NĐ 05/2015 (cần đối chiếu)")]
        note = "Cách tính theo NĐ 05/2015, cần đối chiếu."

    steps = [
        f"Tổng thời gian làm việc: {_num(total)} tháng.",
        f"Trừ {_num(insured)} tháng đã đóng BHTN: còn {_num(net)} tháng.",
        f"{_num(net)} tháng = {_num(whole)} năm + {_num(remainder)} tháng → {rounding}.",
        f"Thời gian tính trợ cấp: {_num(years)} năm.",
    ]
    return _result(version, float(years), "năm", steps, basis, note)


def severance(
    avg_salary_6m: Any,
    years: Any,
    *,
    event_date: date | str | None = None,
    db: Any = None,
) -> dict:
    """Trợ cấp thôi việc = 0,5 × lương bình quân 6 tháng × số năm."""
    version = version_at(event_date)
    salary = _money(avg_salary_6m, "avg_salary_6m")
    worked = _years(years)
    amount = Decimal("0.5") * salary * worked
    value = _round_vnd(amount)

    if version == "blld2019":
        doc_id, node, label = _DOC_2019, "blld2019-d46-k1", "BLLĐ 2019 Điều 46"
    else:
        doc_id, node, label = _DOC_2012, "blld2012-d48-k1", "BLLĐ 2012 Điều 48"

    steps = [
        f"Lương bình quân 6 tháng: {_vnd(salary)} đồng.",
        f"Số năm tính trợ cấp: {_num(worked)} năm.",
        f"0,5 × {_vnd(salary)} × {_num(worked)} = {_vnd(Decimal(value))} đồng.",
    ]
    return _result(
        version, value, "đồng", steps, [_basis(db, doc_id, node, label)]
    )


def job_loss(
    avg_salary_6m: Any,
    years: Any,
    *,
    event_date: date | str | None = None,
    db: Any = None,
) -> dict:
    """Trợ cấp mất việc làm = 1 × lương bình quân × số năm, tối thiểu 2 tháng."""
    version = version_at(event_date)
    salary = _money(avg_salary_6m, "avg_salary_6m")
    worked = _years(years)
    raw = salary * worked
    minimum = salary * 2
    amount = max(raw, minimum)
    value = _round_vnd(amount)

    if version == "blld2019":
        doc_id, node, label = _DOC_2019, "blld2019-d47-k1", "BLLĐ 2019 Điều 47"
    else:
        doc_id, node, label = _DOC_2012, "blld2012-d49-k1", "BLLĐ 2012 Điều 49"

    steps = [
        f"Lương bình quân 6 tháng: {_vnd(salary)} đồng.",
        f"Số năm tính trợ cấp: {_num(worked)} năm.",
        f"1 × {_vnd(salary)} × {_num(worked)} = {_vnd(raw)} đồng.",
        f"Mức tối thiểu 2 tháng lương: {_vnd(minimum)} đồng.",
        f"Áp dụng mức cao hơn: {_vnd(Decimal(value))} đồng.",
    ]
    return _result(
        version, value, "đồng", steps, [_basis(db, doc_id, node, label)]
    )


def unlawful_dismissal(
    monthly_salary: Any,
    days_not_working: int,
    notice_days_missing: int = 0,
    daily_salary: Any | None = None,
    *,
    event_date: date | str | None = None,
    db: Any = None,
) -> dict:
    """Tiền người sử dụng lao động phải trả khi đơn phương chấm dứt trái pháp luật."""
    version = version_at(event_date)
    salary = _money(monthly_salary, "monthly_salary")
    days = _int(days_not_working, "days_not_working")
    missing = _int(notice_days_missing, "notice_days_missing")
    assumed = daily_salary is None
    daily = salary / Decimal(26) if assumed else _money(daily_salary, "daily_salary")

    wages = daily * days
    minimum = salary * 2
    notice = daily * missing
    total = wages + minimum + notice
    value = _round_vnd(total)

    if version == "blld2019":
        doc_id, node, label = _DOC_2019, "blld2019-d41-k1", "BLLĐ 2019 Điều 41 khoản 1"
    else:
        doc_id, node, label = _DOC_2012, "blld2012-d42-k1", "BLLĐ 2012 Điều 42 khoản 1"

    steps = [
        f"Tiền lương ngày: {_vnd(daily)} đồng."
        + (" (giả định = lương tháng / 26)" if assumed else ""),
        f"Lương những ngày không được làm việc: {_vnd(daily)} × {_num(days)} = {_vnd(wages)} đồng.",
        f"Ít nhất 2 tháng lương: 2 × {_vnd(salary)} = {_vnd(minimum)} đồng.",
        f"Lương những ngày thiếu báo trước: {_vnd(daily)} × {_num(missing)} = {_vnd(notice)} đồng.",
        f"Tổng cộng: {_vnd(Decimal(value))} đồng.",
    ]
    note = "Có thể còn khoản đóng bảo hiểm và trợ cấp thôi việc; cần đối chiếu."
    if assumed:
        note = "daily_salary mặc định = lương tháng / 26 (giả định). " + note
    return _result(
        version, value, "đồng", steps, [_basis(db, doc_id, node, label)], note
    )


def _plus_one_year(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29/02 -> 28/02 năm sau
        return day.replace(year=day.year + 1, day=28)


def limitation(
    discovered_on: date | str,
    dispute: str = "individual",
    *,
    event_date: date | str | None = None,
    db: Any = None,
) -> dict:
    """Thời hiệu 1 năm yêu cầu giải quyết tranh chấp lao động cá nhân."""
    discovered = _as_date(discovered_on, "discovered_on")
    if dispute != "individual":
        raise ValueError("chỉ hỗ trợ tranh chấp lao động cá nhân (dispute='individual')")
    version = version_at(event_date if event_date is not None else discovered)
    deadline = _plus_one_year(discovered)
    today = date.today()
    days_left = (deadline - today).days

    if version == "blld2019":
        doc_id, node, label = _DOC_2019, "blld2019-d190-k1", "BLLĐ 2019 Điều 190 khoản 1"
    else:
        doc_id, node, label = _DOC_2012, "blld2012-d202-k1", "BLLĐ 2012 Điều 202 khoản 1"

    steps = [
        f"Ngày phát hiện vi phạm: {_vn_date(discovered)}.",
        f"Thời hiệu 1 năm → hạn cuối: {_vn_date(deadline)}.",
        f"Còn {_num(days_left)} ngày tính từ hôm nay ({_vn_date(today)}).",
    ]
    result = _result(
        version,
        days_left,
        "ngày còn lại",
        steps,
        [_basis(db, doc_id, node, label)],
        "Tranh chấp lao động tập thể có thời hiệu khác; cần đối chiếu.",
    )
    result["deadline"] = deadline.isoformat()
    result["days_left"] = days_left
    return result
