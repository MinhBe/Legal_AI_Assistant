"""Che PII cho bản chép lời chữ thường (lô ghi âm 18/11/2026)."""

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
