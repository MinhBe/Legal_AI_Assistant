"""I1 — bảng tình tiết, câu hỏi lại và máy tính gọi từ câu trả lời (router giả)."""

from __future__ import annotations

from datetime import date

from app.agent import facts, guard, qa
from app.calc import labor

EVENT = date(2023, 6, 30)


def _fact(value, confidence=0.9, source="câu hỏi"):
    return {"value": value, "source": source, "confidence": confidence}


class _Router:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error

    def extract_json(self, msgs, task="route"):
        assert task == "route"
        if self.error:
            raise self.error
        return self.payload


# ---- extract ----


def test_extract_keeps_high_confidence_and_lets_code_override_date_and_money():
    payload = {
        "contract_type": _fact("xac_dinh_thoi_han"),
        "term_months": _fact("12", confidence=0.7),
        "event_date": _fact("2021-05-05"),
        "monthly_salary": _fact(5_000_000, confidence=0.6),
        "notice_given_days": _fact(0, confidence=0.2),  # dưới ngưỡng -> bỏ
        "act": _fact("sa_thai", source="hội thoại"),
        "procedure": _fact("chưa họp xử lý kỷ luật", confidence=0.4),  # bỏ
    }
    fx = facts.extract(
        _Router(payload), "Bị sa thải ngày 20/12/2020, lương 10 triệu đồng, hợp đồng 12 tháng"
    )

    assert "notice_given_days" not in fx and "procedure" not in fx
    assert fx["term_months"]["value"] == 12
    assert fx["act"]["source"] == "hội thoại"
    assert fx["contract_type"]["value"] == "xac_dinh_thoi_han"
    # code thắng LLM: ngày sự kiện lấy từ câu hỏi, tiền parse từ "10 triệu"
    assert fx["event_date"]["value"] == "2020-12-20"
    assert fx["monthly_salary"]["value"] == 10_000_000
    assert fx["monthly_salary"]["source"] == facts.SOURCE_QUESTION


def test_extract_marks_masked_money_without_unmasking():
    payload = {"monthly_salary": _fact("[TIỀN_1]", confidence=0.8)}
    fx = facts.extract(_Router(payload), "Lương tháng của tôi là [TIỀN_1]")
    assert fx["monthly_salary"] == {
        "value": "[TIỀN_1]", "source": facts.SOURCE_MASKED, "confidence": 0.8,
    }


def test_extract_returns_empty_dict_when_router_fails():
    assert facts.extract(_Router(error=RuntimeError("Dahl lỗi")), "bị sa thải") == {}


# ---- follow_ups ----


def test_follow_ups_asks_two_decisive_fields_for_dismissal():
    fx = {"act": _fact("sa_thai")}
    ups = facts.follow_ups(fx, "Tôi bị sa thải, giờ kiện được không?")
    assert ups == [facts.QUESTIONS["contract_type"], facts.QUESTIONS["start_date"]]


def test_follow_ups_silent_when_everything_is_known():
    fx = {
        "act": _fact("sa_thai"),
        "contract_type": _fact("khong_xac_dinh_thoi_han"),
        "start_date": _fact("2019-01-01"),
        "monthly_salary": _fact(10_000_000),
    }
    assert facts.follow_ups(fx, "Tôi bị sa thải thì được bồi thường bao nhiêu?") == []


def test_follow_ups_never_more_than_two_questions():
    ups = facts.follow_ups({}, "Trợ cấp thôi việc và báo trước khi công ty sa thải?")
    assert 0 < len(ups) <= 2


# ---- calculations ----


def test_severance_matches_direct_calc_call():
    fx = {
        "monthly_salary": _fact(10_000_000),
        "start_date": _fact("2019-01-01"),
        "end_date": _fact("2023-06-30"),
    }
    items = facts.calculations(fx, "Trợ cấp thôi việc của tôi là bao nhiêu?", EVENT)
    assert len(items) == 1
    item = items[0]
    years = labor.service_years("2019-01-01", "2023-06-30", 0, event_date=EVENT)["value"]
    direct = labor.severance(10_000_000, years, event_date=EVENT)
    assert item["kind"] == "severance"
    assert item["value"] == direct["value"]
    assert item["basis"] and item["basis"][0]["label"]
    assert item["steps"]


def test_severance_needs_salary():
    fx = {"start_date": _fact("2019-01-01"), "end_date": _fact("2023-06-30")}
    assert facts.calculations(fx, "Trợ cấp thôi việc được bao nhiêu?", EVENT) == []


# ---- pipeline: sự kiện facts / calc đi trước verifier ----


class _PipelineRouter:
    def extract_json(self, msgs, task="route"):
        return {
            "act": _fact("sa_thai"),
            "contract_type": _fact("khong_xac_dinh_thoi_han"),
            "start_date": _fact("2019-01-01"),
            "end_date": _fact("2020-06-30"),
            "monthly_salary": _fact(10_000_000),
        }

    def chat(self, msgs, task, temperature=0.0, parse=None):
        text = '{"summary": "Sa thải trái pháp luật.", "citation_node_ids": ["h1"]}'
        return type("R", (), {"data": parse(text)})()


def test_answer_emits_facts_and_calc_before_verifier(monkeypatch):
    hit = {"node_id": "h1", "doc_id": "blld2019", "display": "Điều 41", "text": "..."}

    class _Session:
        def close(self):
            pass

    monkeypatch.setattr(qa, "get_router", lambda: _PipelineRouter())
    monkeypatch.setattr(qa, "SessionLocal", _Session)
    monkeypatch.setattr(qa, "search_with_history", lambda *a, **k: [hit])
    monkeypatch.setattr(qa, "_timeframe", lambda *a, **k: {})
    monkeypatch.setattr(
        qa, "_run_verify",
        lambda *a, **k: {"ok": True, "checked": 1, "problems": [], "dropped": []},
    )
    monkeypatch.setattr(
        guard, "classify", lambda *a: {"category": guard.LEGAL, "suggested": "", "reason": ""}
    )

    events = list(qa.answer_with_citations(
        "Tôi bị sa thải ngày 20/12/2020, lương 10 triệu, làm từ 2019 đến 30/06/2020, "
        "trợ cấp thôi việc bao nhiêu?"
    ))
    kinds = [e for e, _ in events]

    assert "facts" in kinds and "calc" in kinds
    assert kinds.index("facts") < kinds.index("verifier")
    assert kinds.index("calc") < kinds.index("verifier")

    fx = next(d for e, d in events if e == "facts")
    assert fx["facts"]["event_date"]["value"] == "2020-12-20"
    # câu hỏi không nói loại hợp đồng (LLM giả có đoán) -> code bỏ giá trị đoán và hỏi lại
    assert fx["follow_ups"] == [facts.QUESTIONS["contract_type"]]

    items = next(d for e, d in events if e == "calc")["items"]
    assert {i["kind"] for i in items} == {"severance", "unlawful_dismissal"}


def test_code_fills_start_end_and_drops_guessed_contract_type():
    from app.agent import facts as F

    class R:
        def extract_json(self, *a, **k):
            return {"contract_type": {"value": "khong_xac_dinh_thoi_han", "source": "câu hỏi", "confidence": 0.9}}

    msg = "Tôi làm từ ngày 01/01/2019 đến ngày 30/06/2023 thì nghỉ, lương 10 triệu"
    fx = F.extract(R(), msg)
    assert fx["start_date"]["value"] == "2019-01-01" and fx["end_date"]["value"] == "2023-06-30"
    assert "contract_type" not in fx  # câu hỏi không nói loại hợp đồng
    fx2 = F.extract(R(), msg + ", hợp đồng xác định thời hạn 24 tháng")
    assert fx2["contract_type"]["value"] == "xac_dinh_thoi_han"
