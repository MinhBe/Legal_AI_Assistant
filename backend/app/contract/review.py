"""Rà soát hợp đồng lao động: tách điều khoản, trích số liệu, so với BLLĐ 2019.

Toàn bộ là code xác định: cùng đầu vào cho cùng kết quả, mỗi phát hiện kèm căn cứ.
Không gửi nội dung hợp đồng ra ngoài. Kết quả luôn cần luật sư đối chiếu.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Any

from app.contract import rules_data as R

WARNING = "Kết quả rà soát tự động — cần luật sư đối chiếu"
HIGH, MEDIUM, LOW = "high", "medium", "low"
_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}

_CLAUSE = re.compile(r"(?im)^\s*(điều|điều khoản|mục)\s+(\d+)\s*[\.:\-–]?\s*(.*)$")
_NUM = r"(\d{1,3}(?:[\.,]\d{3})+|\d+(?:[\.,]\d+)?)"


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text or "").lower()


def _to_number(raw: str) -> float:
    raw = raw.strip()
    if re.fullmatch(r"\d{1,3}(?:[\.,]\d{3})+", raw):
        return float(re.sub(r"[\.,]", "", raw))
    return float(raw.replace(",", "."))


def _basis(article: int, clause: int | None = None, point: str | None = None, *,
           doc_id: str = R.BLLD, name: str = R.BLLD_NAME, db: Any = None) -> dict:
    label = f"{name} Điều {article}" + (f" khoản {clause}" if clause else "") + (
        f" điểm {point}" if point else "")
    item: dict[str, Any] = {"doc_id": doc_id, "label": label}
    node_id = f"{doc_id}-d{article}" + (f"-k{clause}" if clause else "")
    if db is not None:
        from app.db.models import LegalNode

        if db.get(LegalNode, node_id) is not None:
            item["node_id"] = node_id
    return item


# ---------- tách điều khoản ----------
def split_clauses(text: str) -> list[dict[str, Any]]:
    """Tách theo dòng "Điều N ...". Không có thì cả văn bản là một khối."""
    text = unicodedata.normalize("NFC", text or "")
    marks = list(_CLAUSE.finditer(text))
    if not marks:
        return [{"no": None, "title": "", "start": 0, "text": text.strip()}]
    out = []
    if marks[0].start() > 0 and text[: marks[0].start()].strip():
        out.append({"no": None, "title": "Phần đầu", "start": 0, "text": text[: marks[0].start()].strip()})
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append({"no": int(m.group(2)), "title": m.group(3).strip(), "start": m.start(),
                    "text": text[m.start():end].strip()})
    return out


def _clause_of(clauses: list[dict[str, Any]], pos: int) -> int | None:
    found = None
    for c in clauses:
        if c["start"] <= pos:
            found = c["no"]
    return found


# ---------- trích số liệu ----------
def _first(pattern: str, text: str) -> re.Match | None:
    return re.search(pattern, text, flags=re.IGNORECASE)


def _duration_days(value: float, unit: str) -> float:
    unit = unit.lower()
    if unit.startswith("tháng"):
        return value * 30
    if unit.startswith("tuần"):
        return value * 7
    if unit.startswith("năm"):
        return value * 365
    return value


def extract_facts(text: str) -> dict[str, Any]:
    t = _norm(text)
    facts: dict[str, Any] = {}

    if "không xác định thời hạn" in t:
        facts["contract_type"] = "indefinite"
    elif m := _first(r"(?:thời hạn(?: hợp đồng)?(?: là)?|xác định thời hạn)\D{0,20}?" + _NUM + r"\s*(tháng|năm)", t):
        months = _to_number(m.group(1)) * (12 if m.group(2).startswith("năm") else 1)
        facts["contract_type"] = "fixed"
        facts["term_months"] = months
        facts["_pos_term"] = m.start()

    if m := _first(r"thử việc\D{0,40}?" + _NUM + r"\s*(ngày|tháng|tuần)", t):
        facts["probation_days"] = _duration_days(_to_number(m.group(1)), m.group(2))
        facts["_pos_probation"] = m.start()
    if m := _first(r"(?:lương|tiền lương)\s*(?:trong thời gian\s*)?thử việc\D{0,40}?" + _NUM + r"\s*%", t):
        facts["probation_pay_pct"] = _to_number(m.group(1))
        facts["_pos_probation_pay"] = m.start()

    if m := _first(r"(?:mức lương|lương cơ bản|tiền lương)[^\n%]{0,40}?" + _NUM + r"\s*(?:đồng|vnđ|vnd|đ\b)", t):
        facts["salary"] = _to_number(m.group(1))
        facts["_pos_salary"] = m.start()
    if m := _first(r"vùng\s+(iv|iii|ii|i)\b", t):
        facts["region"] = m.group(1).upper()

    if m := _first(_NUM + r"\s*giờ\s*(?:/|một|mỗi|trên)\s*ngày", t):
        facts["hours_day"] = _to_number(m.group(1))
        facts["_pos_hours_day"] = m.start()
    if m := _first(_NUM + r"\s*giờ\s*(?:/|một|mỗi|trên)\s*tuần", t):
        facts["hours_week"] = _to_number(m.group(1))
        facts["_pos_hours_week"] = m.start()
    if m := _first(r"(?:làm thêm|tăng ca)\D{0,40}?" + _NUM + r"\s*giờ\s*(?:/|một|mỗi|trên)\s*tháng", t):
        facts["ot_month"] = _to_number(m.group(1))
        facts["_pos_ot"] = m.start()
    if m := _first(r"(?:nghỉ hằng năm|nghỉ hàng năm|nghỉ phép năm|phép năm|nghỉ phép)\D{0,40}?" + _NUM + r"\s*ngày", t):
        facts["annual_leave"] = _to_number(m.group(1))
        facts["_pos_leave"] = m.start()
    if m := _first(r"(?:người lao động|bên b)[^\n]{0,80}?(?:nghỉ việc|chấm dứt|đơn phương)[^\n]{0,80}?báo trước\D{0,20}?"
                   + _NUM + r"\s*ngày", t):
        facts["employee_notice_days"] = _to_number(m.group(1))
        facts["_pos_notice"] = m.start()
    return facts


# ---------- luật kiểm ----------
def _finding(rule: str, severity: str, message: str, suggestion: str, basis: list[dict],
             clause: int | None = None, quote: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "clause": clause, "message": message,
            "suggestion": suggestion, "basis": basis, "quote": quote}


def _quote(text: str, pos: int | None, width: int = 140) -> str:
    if pos is None:
        return ""
    flat = unicodedata.normalize("NFC", text)
    line_end = flat.find("\n", pos)
    return flat[pos: line_end if line_end != -1 else pos + width][:width].strip()


def min_wage_at(day: date, region: str) -> dict | None:
    pick = None
    for row in R.MIN_WAGE:
        if row["valid_from"] <= day:
            pick = row
    if pick is None or region not in pick["by_region"]:
        return None
    return {"amount": pick["by_region"][region], "doc_id": pick["doc_id"], "label": pick["label"],
            "valid_from": pick["valid_from"].isoformat()}


def _probation_group(t: str) -> tuple[str, int, str] | None:
    """Nhóm công việc theo từ khoá; None nếu hợp đồng không nói rõ."""
    for key, days, label, words in R.PROBATION_MAX:
        if words and any(w in t for w in words):
            return key, days, label
    return None


def check(text: str, as_of: date | None = None, db: Any = None) -> dict[str, Any]:
    day = as_of or date.today()
    t = _norm(text)
    clauses = split_clauses(text)
    facts = extract_facts(text)
    pos = lambda k: facts.get(f"_pos_{k}")  # noqa: E731
    at = lambda k: _clause_of(clauses, pos(k)) if pos(k) is not None else None  # noqa: E731
    b = lambda *a, **kw: _basis(*a, db=db, **kw)  # noqa: E731
    out: list[dict[str, Any]] = []

    # 1. nội dung bắt buộc
    missing = []
    for point, label, words in R.REQUIRED:
        if not any(w in t for w in words):
            missing.append({"point": point, "label": label, "basis": b(21, 1, point)})
    for m in missing:
        out.append(_finding("missing_content", MEDIUM, f"Thiếu nội dung bắt buộc: {m['label']}.",
                            "Bổ sung điều khoản tương ứng.", [m["basis"]]))

    # 2. điều khoản cấm (Điều 17)
    if re.search(r"giữ (?:bản chính|bản gốc|văn bằng|bằng cấp|chứng chỉ|giấy tờ tùy thân|giấy tờ tuỳ thân|cccd|căn cước)", t):
        p = re.search(r"giữ (?:bản chính|bản gốc|văn bằng|bằng cấp|chứng chỉ|giấy tờ|cccd|căn cước)", t)
        out.append(_finding("hold_documents", HIGH,
                            "Người sử dụng lao động giữ giấy tờ tuỳ thân, văn bằng, chứng chỉ của người lao động là hành vi bị cấm.",
                            "Bỏ điều khoản; chỉ được xem/sao chụp.", [b(17, 1, "a")], _clause_of(clauses, p.start()),
                            _quote(text, p.start())))
    if p := re.search(r"(?:đặt cọc|ký quỹ|tiền cọc|biện pháp bảo đảm bằng tiền)", t):
        out.append(_finding("deposit", HIGH,
                            "Buộc người lao động đặt cọc, ký quỹ hoặc bảo đảm bằng tiền để thực hiện hợp đồng là hành vi bị cấm.",
                            "Bỏ khoản đặt cọc.", [b(17, 1, "b")], _clause_of(clauses, p.start()), _quote(text, p.start())))
    if p := re.search(r"(?:phạt tiền|trừ lương|khấu trừ lương|cắt lương)[^\n]{0,60}(?:vi phạm|đi muộn|kỷ luật|nội quy)", t):
        out.append(_finding("fine_instead_of_discipline", HIGH,
                            "Phạt tiền, cắt lương thay cho xử lý kỷ luật lao động là hành vi bị cấm.",
                            "Thay bằng các hình thức kỷ luật luật định (khiển trách, kéo dài nâng lương, cách chức, sa thải).",
                            [b(127, 3)], _clause_of(clauses, p.start()), _quote(text, p.start())))

    # 3. thời hạn hợp đồng
    if facts.get("contract_type") == "fixed" and facts.get("term_months", 0) > R.MAX_FIXED_TERM_MONTHS:
        out.append(_finding("term_too_long", HIGH,
                            f"Hợp đồng xác định thời hạn {facts['term_months']:g} tháng, vượt mức tối đa 36 tháng.",
                            "Rút xuống tối đa 36 tháng hoặc chuyển sang hợp đồng không xác định thời hạn.",
                            [b(20, 1, "b")], at("term"), _quote(text, pos("term"))))

    # 4. thử việc
    if "probation_days" in facts:
        grp = _probation_group(t)
        if grp is None:
            limit, group = R.PROBATION_MAX[0][1], "mọi loại công việc"
            if facts["probation_days"] > R.PROBATION_MAX[-1][1]:
                out.append(_finding("probation_group_unknown", LOW,
                                    "Chưa rõ chức danh cần trình độ gì nên chưa biết mức thử việc tối đa (6–180 ngày).",
                                    "Ghi rõ chức danh và trình độ yêu cầu.", [b(25)], at("probation")))
        else:
            _, limit, group = grp
        if facts.get("contract_type") == "fixed" and facts.get("term_months", 99) < 1:
            out.append(_finding("probation_short_contract", HIGH,
                                "Hợp đồng dưới 1 tháng không được thoả thuận thử việc.", "Bỏ điều khoản thử việc.",
                                [b(24, 3)], at("probation"), _quote(text, pos("probation"))))
        if facts["probation_days"] > limit:
            out.append(_finding("probation_too_long", HIGH,
                                f"Thử việc {facts['probation_days']:g} ngày, vượt mức tối đa {limit} ngày cho {group}.",
                                f"Rút thời gian thử việc xuống không quá {limit} ngày.",
                                [b(25)], at("probation"), _quote(text, pos("probation"))))
    if "probation_pay_pct" in facts and facts["probation_pay_pct"] < R.PROBATION_MIN_PAY_PCT:
        out.append(_finding("probation_pay_low", HIGH,
                            f"Lương thử việc {facts['probation_pay_pct']:g}% thấp hơn mức tối thiểu 85% lương công việc.",
                            "Nâng lương thử việc lên ít nhất 85%.", [b(26)], at("probation_pay"),
                            _quote(text, pos("probation_pay"))))

    # 5. lương tối thiểu vùng
    if "salary" in facts:
        region = facts.get("region")
        mw = min_wage_at(day, region) if region else None
        if mw and facts["salary"] < mw["amount"]:
            out.append(_finding("below_min_wage", HIGH,
                                f"Mức lương {facts['salary']:,.0f} đồng thấp hơn lương tối thiểu vùng {region} "
                                f"({mw['amount']:,.0f} đồng, áp dụng từ {mw['valid_from']}).".replace(",", "."),
                                "Nâng lương lên ít nhất mức tối thiểu vùng.",
                                [b(90, 2), {"doc_id": mw["doc_id"], "label": mw["label"]}], at("salary"),
                                _quote(text, pos("salary"))))
        elif not region:
            out.append(_finding("region_unknown", LOW,
                                "Chưa xác định được vùng lương tối thiểu nên chưa so mức lương.",
                                "Ghi rõ địa điểm làm việc (tỉnh/huyện) để đối chiếu vùng.", [b(90, 2)], at("salary")))

    # 6. thời giờ làm việc
    if facts.get("hours_day", 0) > R.MAX_HOURS_DAY:
        out.append(_finding("hours_day", MEDIUM,
                            f"Thời giờ làm việc bình thường {facts['hours_day']:g} giờ/ngày, vượt 8 giờ/ngày.",
                            "Giữ ở 8 giờ/ngày; phần vượt phải tính là làm thêm giờ.", [b(105, 1)], at("hours_day"),
                            _quote(text, pos("hours_day"))))
    if facts.get("hours_week", 0) > R.MAX_HOURS_WEEK:
        out.append(_finding("hours_week", MEDIUM,
                            f"Thời giờ làm việc {facts['hours_week']:g} giờ/tuần, vượt 48 giờ/tuần.",
                            "Giảm xuống tối đa 48 giờ/tuần.", [b(105, 1)], at("hours_week"),
                            _quote(text, pos("hours_week"))))
    if facts.get("ot_month", 0) > R.MAX_OT_MONTH:
        out.append(_finding("overtime_month", MEDIUM,
                            f"Làm thêm {facts['ot_month']:g} giờ/tháng, vượt 40 giờ/tháng.",
                            "Giới hạn làm thêm tối đa 40 giờ/tháng.", [b(107, 2, "b")], at("ot"), _quote(text, pos("ot"))))
    if "annual_leave" in facts and facts["annual_leave"] < R.MIN_ANNUAL_LEAVE:
        out.append(_finding("annual_leave_low", MEDIUM,
                            f"Nghỉ hằng năm {facts['annual_leave']:g} ngày, ít hơn 12 ngày làm việc.",
                            "Nâng lên ít nhất 12 ngày làm việc/năm (điều kiện bình thường).", [b(113, 1, "a")],
                            at("leave"), _quote(text, pos("leave"))))

    # 7. báo trước khi người lao động nghỉ việc
    if "employee_notice_days" in facts:
        ctype = facts.get("contract_type")
        if ctype == "indefinite":
            limit = R.EMPLOYEE_NOTICE_MAX["indefinite"]
        elif ctype == "fixed" and facts.get("term_months", 0) < 12:
            limit = R.EMPLOYEE_NOTICE_MAX["fixed_lt12"]
        else:
            limit = R.EMPLOYEE_NOTICE_MAX["fixed_12_36"]
        if facts["employee_notice_days"] > limit:
            out.append(_finding("notice_too_long", MEDIUM,
                                f"Buộc người lao động báo trước {facts['employee_notice_days']:g} ngày, dài hơn mức luật định ({limit} ngày).",
                                f"Giảm thời hạn báo trước xuống {limit} ngày; điều khoản bất lợi hơn luật không có hiệu lực.",
                                [b(35, 1)], at("notice"), _quote(text, pos("notice"))))

    out.sort(key=lambda f: (_ORDER[f["severity"]], f["clause"] or 0))
    counts = {s: sum(1 for f in out if f["severity"] == s) for s in (HIGH, MEDIUM, LOW)}
    notes = [WARNING]
    if day < date(2021, 1, 1):
        notes.append("Ngày áp dụng trước 01/01/2021: luật kiểm theo BLLĐ 2019, cần đối chiếu BLLĐ 2012.")
    return {
        "as_of": day.isoformat(),
        "clauses": [{k: v for k, v in c.items() if k != "start"} for c in clauses],
        "facts": {k: v for k, v in facts.items() if not k.startswith("_")},
        "missing": missing,
        "findings": out,
        "counts": counts,
        "verdict": "risky" if counts[HIGH] else ("review" if counts[MEDIUM] else "ok"),
        "note": " ".join(notes),
    }
