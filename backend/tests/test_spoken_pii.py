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
