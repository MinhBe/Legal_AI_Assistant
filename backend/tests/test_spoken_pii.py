"""Che PII cho bản chép lời chữ thường (lô ghi âm 18/11/2026)."""
import json

from app.audio.spoken_pii import mask_spoken, ner_values


class FakeRouter:
    def __init__(self, text: str) -> None:
        self.text = text

    def chat(self, messages, **_kw):
        return type("R", (), {"text": self.text})()


def test_lowercase_name_after_honorific_and_given_name_reuse():
    m: dict[str, str] = {}
    out = mask_spoken("xin giới thiệu luật sư đỗ đăng khoa. thầy khoa đã tư vấn", mapping=m)
    assert "khoa" not in out and "đỗ" not in out
    assert out.count("[TÊN_1]") == 2


def test_social_display_name_and_spoken_phone():
    m: dict[str, str] = {}
    out = mask_spoken(
        "chào bạn bảy bảy nguyễn số của tôi là không chín một hai ba bốn năm sáu bảy tám",
        mapping=m,
    )
    assert "nguyễn" not in out and "không chín một" not in out
    assert "[SỐ_1]" in out


def test_ordinary_words_and_areas_survive():
    m: dict[str, str] = {}
    text = "cha mẹ có ba trăm mét vuông đất ở muốn chia cho ba người con"
    assert mask_spoken(text, mapping=m) == text


def test_ner_drops_implausible_labels_and_values_not_in_text():
    text = "anh khoa có ba trăm mét vuông, công ty luật hưng thịnh tư vấn"
    router = FakeRouter(
        '{"items": [{"type": "STK", "text": "ba trăm mét vuông"},'
        ' {"type": "TỔ_CHỨC", "text": "công ty luật hưng thịnh"},'
        ' {"type": "TÊN", "text": "người không có trong đoạn"}]}'
    )
    assert ner_values(router, text) == [("TỔ_CHỨC", "công ty luật hưng thịnh")]
    m: dict[str, str] = {}
    out = mask_spoken(text, mapping=m, router=router)
    assert "hưng thịnh" not in out and "ba trăm mét vuông" in out


def test_ner_failure_falls_back_to_rules():
    m: dict[str, str] = {}
    out = mask_spoken("chị nguyễn thị lan hỏi", mapping=m, router=FakeRouter("không phải json"))
    assert "lan" not in out


def test_single_syllable_name_only_after_honorific_and_generic_org_rejected():
    text = "luật sư phương nói tặng cho đối phương, ra văn phòng công chứng"
    router = FakeRouter(
        '{"items": [{"type": "TÊN", "text": "phương"},'
        ' {"type": "TỔ_CHỨC", "text": "văn phòng công chứng"}]}'
    )
    m: dict[str, str] = {}
    out = mask_spoken(text, mapping=m, router=router)
    assert "luật sư [TÊN_1]" in out and "đối phương" in out
    assert "văn phòng công chứng" in out


def test_org_core_masked_when_split_across_segments():
    router = FakeRouter('{"items": [{"type": "TỔ_CHỨC", "text": "công ty luật hân vượng"}]}')
    m: dict[str, str] = {}
    from app.audio.spoken_pii import add_ner

    add_ner(router, "giám đốc công ty luật hân vượng", m)
    assert "hân" not in mask_spoken("Hân Vượng", mapping=m).lower()


def test_media_outlet_does_not_mask_the_word_phap_luat():
    router = FakeRouter('{"items": [{"type": "TỔ_CHỨC", "text": "kênh truyền hình pháp luật"}]}')
    m: dict[str, str] = {}
    out = mask_spoken("các vấn đề về mặt pháp luật", mapping=m, router=router)
    assert out == "các vấn đề về mặt pháp luật"


def test_amounts_dates_and_article_numbers_are_kept():
    m: dict[str, str] = {}
    text = "đánh dưới 5 triệu thì phạt, 100.000.000 đồng, ngày 16/11/2026, khoản 1 Điều 321"
    assert mask_spoken(text, mapping=m) == text


def test_bare_given_names_after_introductions():
    m: dict[str, str] = {}
    out = mask_spoken("câu hỏi đầu tiên của bạn là minh đó là", mapping=m)
    assert "minh" not in out
    out = mask_spoken("Chào bạn Lan Anh, cảm ơn bạn Hùng", mapping=m)
    assert "Lan" not in out and "Hùng" not in out
    assert mask_spoken("chào bạn nhé, tên là gì", mapping=m) == "chào bạn nhé, tên là gì"


def test_public_entities_are_not_masked():
    router = FakeRouter(
        '{"items": [{"type": "TỔ_CHỨC", "text": "eTax Mobile"},'
        ' {"type": "TỔ_CHỨC", "text": "cơ quan thuế"}, {"type": "TỔ_CHỨC", "text": "VTV"},'
        ' {"type": "TỔ_CHỨC", "text": "toà án nhân dân"},'
        ' {"type": "TỔ_CHỨC", "text": "văn phòng đăng ký đất đai"}]}'
    )
    text = "nộp trên eTax Mobile hoặc cơ quan thuế, VTV đưa tin, toà án nhân dân, văn phòng đăng ký đất đai"
    m: dict[str, str] = {}
    assert mask_spoken(text, mapping=m, router=router) == text


def test_id_number_masked_but_separated_amount_kept():
    m: dict[str, str] = {}
    out = mask_spoken("cccd 001203004567 nộp 100.000.000", mapping=m)
    assert "001203004567" not in out and "100.000.000" in out


def test_mask_lines_uses_context_across_segment_boundaries():
    from app.audio.spoken_pii import mask_lines

    m: dict[str, str] = {}
    lines = ["Câu hỏi đầu tiên của bạn là", "Minh đó là cha mẹ có 300 mét vuông đất ở",
             "Giám đốc công ty luật bất động sản", "Hân Vượng"]
    m["[TỔ_CHỨC_1]"] = "công ty luật bất động sản Hân Vượng"
    out = mask_lines(lines, mapping=m)
    assert len(out) == 4
    assert "Minh" not in out[1] and "300 mét vuông" in out[1]
    assert "Hân" not in " ".join(out)


def test_lowercase_words_after_ban_are_not_names():
    from app.audio.spoken_pii import mask_lines

    m: dict[str, str] = {}
    lines = ["Vâng, xin chào các bạn đã gửi lời chào", "Chào bạn Bảy Nguyễn",
             "các bạn đã đặt ở phần bình luận", "đã tới tay bạn đọc"]
    out = mask_lines(lines, mapping=m)
    assert out[0] == lines[0] and out[2] == lines[2] and out[3] == lines[3]
    assert out[1] == "Chào bạn [TÊN_1]"


def test_ner_false_positives_from_7b_are_rejected():
    """Nhãn sai đo trên tệp 1 (18/11/2026): quan hệ gia đình, lĩnh vực, địa danh, đài báo."""
    items = [("TÊN", "cha mẹ"), ("TÊN", "con nuôi"), ("TÊN", "anh"),
             ("TỔ_CHỨC", "đất đai"), ("TỔ_CHỨC", "trợ lý"), ("TỔ_CHỨC", "thành phố hồ chí minh"),
             ("TỔ_CHỨC", "tạp chí kinh tế sài gòn"), ("TỔ_CHỨC", "văn phòng đất đai")]
    text = " ".join(v for _t, v in items) + " và công ty luật hân vượng, luật sư đỗ đăng khoa"
    payload = [{"type": t, "text": v} for t, v in items] + [
        {"type": "TỔ_CHỨC", "text": "công ty luật hân vượng"},
        {"type": "TÊN", "text": "đỗ đăng khoa"}]
    router = FakeRouter(json.dumps({"items": payload}, ensure_ascii=False))
    got = ner_values(router, text)
    assert got == [("TỔ_CHỨC", "công ty luật hân vượng"), ("TÊN", "đỗ đăng khoa")]
    m: dict[str, str] = {}
    from app.audio.spoken_pii import add_ner

    add_ner(router, text, m)
    assert "đất đai" not in m.values() and "sài gòn" not in m.values()
    assert mask_spoken("luật đất đai năm 2024, ở thành phố hồ chí minh", mapping=m) == \
        "luật đất đai năm 2024, ở thành phố hồ chí minh"


def test_livestream_asker_names():
    m: dict[str, str] = {}
    text = ("bạn tùng hỏi là bố đẻ cho tiền, bạn trường có hỏi là, bạn là thúy hỏi là, bạn trời số trời hỏi là, "
            "câu hỏi tiếp của bạn phùng là đất, bạn à am có hỏi là, các bạn thường hỏi là, "
            "bạn ấy hỏi là")
    out = mask_spoken(text, mapping=m)
    for name in ("tùng", "trường", "thúy", "phùng", " am ", "trời"):
        assert name not in out, name
    assert "các bạn thường hỏi" in out and "bạn ấy hỏi" in out and "bạn à [TÊN_" in out


def test_function_words_never_become_names():
    m: dict[str, str] = {"[TÊN_1]": "bảy có"}  # giá trị rác từ lần che cũ
    from app.audio.spoken_pii import _plausible

    assert not _plausible("TÊN", "bảy có") and not _plausible("TÊN", "có")
    out = mask_spoken("bạn có quyền yêu cầu, ông có đất để bán, bạn trường có hỏi", mapping={})
    assert "bạn có quyền" in out and "ông có đất" in out and "trường" not in out
    assert "có hỏi" in out
    del m


def test_new_placeholder_never_overwrites_with_gaps():
    from app.audio.spoken_pii import _new_placeholder

    m = {"[TÊN_1]": "an", "[TÊN_3]": "bình"}  # lỗ ở số 2 sau khi lọc
    ph = _new_placeholder(m, "TÊN", "cường")
    assert ph == "[TÊN_4]" and m["[TÊN_3]"] == "bình" and len(m) == 3


def test_salvage_items_from_truncated_json():
    from app.audio.spoken_pii import salvage_items

    raw = '{"items": [{"text": "Nguyễn Văn An", "type": "TÊN"}, {"type": "TỔ_CHỨC", "text": "Công ty X"}, {"text": "Trần Th'
    assert salvage_items(raw) == [{"text": "Nguyễn Văn An", "type": "TÊN"},
                                  {"text": "Công ty X", "type": "TỔ_CHỨC"}]
    assert salvage_items("") == []
