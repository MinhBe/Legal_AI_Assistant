"""T2 — ngày sự kiện, luật áp dụng tại ngày đó, khung thời gian trong câu trả lời."""

from __future__ import annotations

from datetime import date

import pytest

from app.amend.timeframe import extract_event_date, resolve, summary_lines
from app.amend.versions import backfill, create_tables
from app.db.base import engine

ADVICE = date(2026, 11, 16)


@pytest.fixture(scope="module", autouse=True)
def _tables(db):
    create_tables(engine)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("bị sa thải ngày 20/12/2020", (date(2020, 12, 20), "ngày")),
        ("ngày 20/12/2020", (date(2020, 12, 20), "ngày")),
        ("chấm dứt hợp đồng 20/12/2020", (date(2020, 12, 20), "ngày")),
        ("20-12-2020", (date(2020, 12, 20), "ngày")),
        ("20.12.2020", (date(2020, 12, 20), "ngày")),
        ("ngày 20 tháng 12 năm 2020", (date(2020, 12, 20), "ngày")),
        ("tháng 12/2020", (date(2020, 12, 31), "tháng")),
        ("tháng 12 năm 2020", (date(2020, 12, 31), "tháng")),
        ("tháng 2/2024", (date(2024, 2, 29), "tháng")),
        ("năm 2020", (date(2020, 12, 31), "năm")),
        # số hiệu văn bản và số điều không phải ngày
        ("Điều 25 BLLĐ 2019, Nghị định 145/2020/NĐ-CP, Luật 45/2019/QH14", (None, "")),
        ("không có ngày nào", (None, "")),
    ],
)
def test_extract_event_date_formats(text, expected):
    assert extract_event_date(text, ADVICE) == expected


def test_extract_event_date_picks_latest_past():
    text = "năm 2019 tôi ký hợp đồng, đến ngày 20/12/2020 thì bị sa thải"
    assert extract_event_date(text, ADVICE) == (date(2020, 12, 20), "ngày")


@pytest.mark.parametrize("text", [
    "Theo Bộ luật Lao động năm 2019, thời gian thử việc tối đa là bao lâu?",
    "Nghị định năm 2020 hướng dẫn gì về tiền lương?",
    "BLLĐ năm 2012 quy định thế nào?",
])
def test_law_year_is_not_an_event_date(text):
    assert extract_event_date(text, ADVICE) == (None, "")


def test_law_year_ignored_but_real_event_kept():
    text = "Theo Bộ luật Lao động năm 2019, tôi bị sa thải năm 2022 thì sao?"
    assert extract_event_date(text, ADVICE) == (date(2022, 12, 31), "năm")


def test_extract_event_date_all_future_takes_earliest():
    text = "ngày 20/12/2020 và ngày 20/12/2021"
    assert extract_event_date(text, date(2020, 6, 1)) == (date(2020, 12, 20), "ngày")


@pytest.mark.parametrize("text", ["ngày 31/02/2020", "ngày 20/13/2020", "tháng 13/2020"])
def test_extract_event_date_rejects_impossible_dates(text):
    assert extract_event_date(text, ADVICE) == (None, "")


def test_summary_lines_are_short_and_mention_dates():
    tf = {
        "event_date": "2020-12-20", "event_date_source": "câu hỏi",
        "advice_date": "2026-11-16", "as_of": "2020-12-20",
        "applicable": [{"doc_id": "blld2012", "title": "Bộ luật Lao động 2012"}],
        "changes_after": [{"doc_id": "blld2019", "title": "Bộ luật Lao động 2019",
                           "effective_date": "2021-01-01", "replaces": ["blld2012"]}],
        "upcoming": [], "transition_rules": [],
        "flags": ["Có văn bản mới sau ngày sự kiện, chưa có quy tắc chuyển tiếp: cần luật sư xác nhận"],
    }
    lines = summary_lines(tf)
    assert 1 <= len(lines) <= 4
    assert "Ngày sự kiện: 20/12/2020" in lines[0]
    assert "Bộ luật Lao động 2012" in lines[0]
    assert "01/01/2021" in lines[1]


@pytest.mark.db
def test_resolve_event_2020_uses_the_2012_code(db):
    backfill(db, today=ADVICE)
    tf = resolve(db, date(2020, 12, 20), ADVICE)

    ids = [d["doc_id"] for d in tf["applicable"]]
    assert "blld2012" in ids and "blld2019" not in ids
    changes = [c["doc_id"] for c in tf["changes_after"]]
    assert "blld2019" in changes
    blld2019 = next(c for c in tf["changes_after"] if c["doc_id"] == "blld2019")
    assert blld2019["effective_date"] == "2021-01-01"
    assert "blld2012" in blld2019["replaces"]

    assert [r["doc_key"] for r in tf["transition_rules"]] == ["blld2019"]
    assert tf["as_of"] == "2020-12-20"
    assert tf["event_date_source"] == "câu hỏi"
    assert not any("chưa có quy tắc" in f for f in tf["flags"])


@pytest.mark.db
def test_resolve_without_event_uses_advice_date(db):
    backfill(db, today=ADVICE)
    tf = resolve(db, None, ADVICE)
    ids = [d["doc_id"] for d in tf["applicable"]]
    assert "blld2019" in ids and "nd145_2020" in ids
    assert tf["changes_after"] == []
    assert tf["as_of"] == ADVICE.isoformat()
    assert tf["event_date_source"] == "không nêu — dùng ngày tư vấn"


@pytest.mark.db
def test_answer_uses_event_date_and_yields_timeframe(monkeypatch, db):
    """Router và truy hồi giả: không gọi mạng, không ghi DB."""
    from app.agent import guard, qa

    hit = {"node_id": "blld2012-d41-k1", "display": "Điều 41 (BLLĐ 2012)", "text": "..."}
    seen: dict = {}
    prompts: list = []

    def fake_search(db_, query, *, top_k=5, as_of=None, **kw):
        seen["as_of"] = as_of
        return [hit]

    class Router:
        def chat(self, msgs, task, temperature=0.0, parse=None):
            prompts.append(msgs)
            text = '{"summary": "Sa thải trái pháp luật.", "citation_node_ids": ["blld2012-d41-k1"]}'
            return type("R", (), {"data": parse(text)})()

        def extract_json(self, msgs, task="route"):
            return {"issues": []}

    monkeypatch.setattr(qa, "get_router", Router)
    monkeypatch.setattr(qa, "search_nodes", fake_search)
    monkeypatch.setattr(
        guard, "classify",
        lambda *a: {"category": guard.LEGAL, "suggested": "", "reason": ""},
    )

    events = list(qa.answer_with_citations("Tôi bị sa thải ngày 20/12/2020"))
    kinds = [e for e, _ in events]

    assert seen["as_of"] == date(2020, 12, 20)
    assert "Khung thời gian" in prompts[0][1]["content"]
    assert kinds[-1] == "done"
    assert "timeframe" in kinds
    assert kinds.index("timeframe") > max(i for i, k in enumerate(kinds) if k == "citation")

    tf = next(d for e, d in events if e == "timeframe")
    assert "blld2012" in [d["doc_id"] for d in tf["applicable"]]
