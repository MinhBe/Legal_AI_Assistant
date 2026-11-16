"""Bộ trích dẫn chiếu: phần khó là đoán đúng văn bản đích, không phải bắt con số."""

import pytest

from app.ingestion.references import extract_refs, known_docs_from_db

# bản đồ như known_docs_from_db dựng từ legal_document
KNOWN = {
    "145/2020/nđ-cp": "nd145_2020",
    "45/2019/qh14": "blld2019",
    "10/2012/qh13": "blld2012",
    "bộ luật lao động 2019": "blld2019",
    "bộ luật lao động 2012": "blld2012",
}


def targets(text, src_doc, **kw):
    return [t for t, _ in extract_refs(text, src_doc, **kw)]


def test_bare_reference_stays_in_source_document():
    assert targets("theo quy định tại khoản 2 Điều 35", "blld2019") == ["blld2019-d35-k2"]


def test_explicit_law_name_points_to_labour_code():
    got = targets("Người sử dụng lao động theo khoản 2 Điều 2 của Bộ luật Lao động.", "nd145_2020")
    assert got == ["blld2019-d2-k2"]


def test_this_law_means_the_source_document():
    assert targets("quy định tại Điều 35 của Bộ luật này", "blld2019") == ["blld2019-d35"]


def test_decree_bare_reference_inherits_article_context():
    # Nghị định 145 có tới Điều 115, nên "khoản 3 Điều 12" để trống tên văn bản
    # vẫn khớp được trong chính nó; ngữ cảnh của Điều cha phải kéo nó sang Bộ luật.
    ctx = "Người sử dụng lao động theo khoản 2 Điều 2 của Bộ luật Lao động. Quản lý lao động theo khoản 3 Điều 12."
    got = targets("Quản lý lao động theo khoản 3 Điều 12.", "nd145_2020", article_context=ctx)
    assert got == ["blld2019-d12-k3"]


def test_decree_without_context_falls_back_to_itself():
    assert targets("theo khoản 3 Điều 12", "nd145_2020") == ["nd145_2020-d12-k3"]


def test_point_clause_article_and_lists():
    got = targets("điểm d khoản 1 Điều 35, điểm d khoản 2 Điều 36; khoản 4 Điều 46", "blld2019")
    assert got == ["blld2019-d35-k1-d", "blld2019-d36-k2-d", "blld2019-d46-k4"]


def test_old_code_naming_itself_stays_old():
    assert targets("khoản 1 Điều 37 của Bộ luật Lao động", "blld2012") == ["blld2012-d37-k1"]


def test_repeated_reference_is_reported_once():
    assert targets("Điều 35 và Điều 35", "blld2019") == ["blld2019-d35"]


def test_empty_text():
    assert extract_refs("", "blld2019") == []


# ---------- nhận ra văn bản theo số hiệu / tên (U9) ----------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("khoản 1 Điều 3 Nghị định 145/2020/NĐ-CP", "nd145_2020-d3-k1"),
        ("khoản 1 Điều 3 Nghị định số 145/2020/NĐ-CP", "nd145_2020-d3-k1"),
        ("khoản 1 Điều 3 NĐ 145/2020", "nd145_2020-d3-k1"),
        ("khoản 1 Điều 3 Nghị định 145", "nd145_2020-d3-k1"),
        ("khoản 1 Điều 2 Bộ luật Lao động 2012", "blld2012-d2-k1"),
        ("khoản 1 Điều 2 Bộ luật Lao động năm 2012", "blld2012-d2-k1"),
        ("khoản 1 Điều 2 BLLĐ 2019", "blld2019-d2-k1"),
        ("khoản 1 Điều 2 Luật số 45/2019/QH14", "blld2019-d2-k1"),
    ],
)
def test_doc_number_or_name_after_reference(text, expected):
    assert targets(text, "up_x", known_docs=KNOWN) == [expected]


def test_year_qualified_code_picks_that_year():
    assert targets("Điều 37 Bộ luật Lao động 2012", "nd145_2020", known_docs=KNOWN) == [
        "blld2012-d37"
    ]
    assert targets("Điều 37 Bộ luật Lao động 2019", "nd145_2020", known_docs=KNOWN) == [
        "blld2019-d37"
    ]


def test_bare_doc_mention_is_not_a_node_reference():
    assert extract_refs(
        "Theo Nghị định 145/2020/NĐ-CP và Bộ luật Lao động 2019, ...",
        "up_x",
        known_docs=KNOWN,
    ) == []


def test_numbered_doc_as_inherited_context():
    ctx = "Căn cứ Nghị định 145/2020/NĐ-CP. Quy định chi tiết tại khoản 1 Điều 3."
    assert targets("Quy định chi tiết tại khoản 1 Điều 3.", "up_x", article_context=ctx,
                   known_docs=KNOWN) == ["nd145_2020-d3-k1"]


def test_unknown_doc_number_falls_back_to_source():
    assert targets("khoản 1 Điều 3 Nghị định 999/2099/NĐ-CP", "up_x", known_docs=KNOWN) == [
        "up_x-d3-k1"
    ]


@pytest.mark.db
def test_known_docs_from_db_has_numbers_and_titles(db):
    known = known_docs_from_db(db)
    assert known["145/2020/nd-cp"] == "nd145_2020"
    assert known["45/2019/qh14"] == "blld2019"
    assert known["bo luat lao dong 2012"] == "blld2012"
    assert all(not doc.startswith("up_") for doc in known.values())
