"""Prompt v2 cho bản chép lời: kiểm lược đồ, audit và lưới an toàn (không gọi mô hình)."""

import json

from app.problems import spoken_v2

CORPUS = ["Bộ luật Lao động 2019 (45/2019/QH14)", "Nghị định 145/2020/NĐ-CP"]


def _unit(**kw):
    base = {"domain": "đất đai", "in_scope_labour": "no", "facts": ["Cha mẹ có 300 m² đất ở."],
            "legal_question": "Có tách thửa được không?", "lawyer_says": ["Khả năng cao là tách được."],
            "suggestions": [], "citations": [], "practical_tactics": [], "uncertain": [],
            "start": "02:12", "end": "03:00"}
    return {**base, **kw}


def _fake(stage1: str, stage2: dict):
    replies = iter([json.dumps({"corrected": stage1}, ensure_ascii=False),
                    json.dumps(stage2, ensure_ascii=False)])
    return lambda _messages: next(replies)


def test_run_coerces_minimax_style_types():
    unit = _unit(start=132, suggestions=["Tra quy định tách thửa của tỉnh."],
                 citations=["Luật Đất đai 2024"], facts="Cha mẹ có 300 m² đất ở.")
    out = spoken_v2.run(_fake("[02:12] …", {"units": [unit]}), {"A": "x"}, CORPUS)
    assert out["errors"] == [] and len(out["units"]) == 1
    u = out["units"][0]
    assert u["start"] == "132" and u["facts"] == ["Cha mẹ có 300 m² đất ở."]
    assert u["suggestions"][0]["needs_lawyer_review"] is True
    assert u["citations"][0]["doc"] == "Luật Đất đai 2024"


def test_audit_flags_invented_numbers_and_literal_marks():
    unit = _unit(
        lawyer_says=["Theo Điều 29 thì [?a/b]."],
        citations=[{"doc": "Luật Đất đai 2013", "article": "Điều 29", "status": "verified_in_corpus",
                    "source": "model"}],
        suggestions=[{"text": "Xem Nghị định 43/2014.", "needs_lawyer_review": True}],
    )
    issues = spoken_v2.audit({"corrected": "300 mét vuông", "units": [unit]}, "300 mét", CORPUS)
    text = " ".join(issues)
    assert "verified_in_corpus" in text and "Điều 29" in text and "[?a/b]" in text
    assert "43/2014" in text


def test_audit_accepts_numbers_from_sources():
    unit = _unit(citations=[{"doc": "Bộ luật Hình sự", "article": "khoản 1 Điều 321",
                             "status": "outside_corpus_unverified", "source": "audio"}],
                 lawyer_says=["Từ 5 triệu đồng thì khởi tố theo khoản 1 Điều 321."])
    src = "xử lý ở khoản 1 tội đánh bạc đều 321 mô lĩnh sự, 5 triệu"
    assert spoken_v2.audit({"corrected": "", "units": [unit]}, src, CORPUS) == []


def test_enforce_downgrades_and_strips_memory_articles():
    result = {"units": [_unit(citations=[
        {"doc": "Luật Đất đai 2013", "article": "Điều 29", "status": "verified_in_corpus",
         "source": "model"},
        {"doc": "Bộ luật Lao động 2019", "article": "Điều 35", "status": "verified_in_corpus",
         "source": "audio"},
    ], suggestions=[{"text": "x", "needs_lawyer_review": False}])]}
    changes = spoken_v2.enforce(result, CORPUS)
    c1, c2 = result["units"][0]["citations"]
    assert c1["status"] == "outside_corpus_unverified" and c1["article"] == ""
    assert c2["status"] == "verified_in_corpus" and c2["article"] == "Điều 35"
    assert result["units"][0]["suggestions"][0]["needs_lawyer_review"] is True
    assert len(changes) == 2
