"""Che PII cho bản chép lời giọng nói.

`gateway.pii.mask` bắt tên dựa vào chữ hoa và số viết bằng chữ số. Bản chép lời của
Whisper, nhất là PhoWhisper, toàn chữ thường và đọc số thành chữ ("không chín một hai…").
Đo trên lô ghi âm 18/11/2026: lượt che cũ không che được gì, kể cả tên người hỏi.

Chạy ba lớp, giá trị nào bị bắt ở lớp nào cũng dùng chung một ánh xạ:
1. Tuỳ chọn: mô hình TRONG MÁY (mức A) liệt kê tên người, tên doanh nghiệp tư, số
   điện thoại/tài khoản, địa chỉ; mỗi giá trị được thay ở mọi nơi nó xuất hiện.
2. `gateway.pii.mask` như cũ.
3. Luật cho chữ thường: tên sau từ xưng hô có họ Việt phổ biến, tên hiển thị kiểu mạng
   xã hội, dãy số đọc thành chữ, tên gọi ("thầy khoa") của người đã che.
"""

from __future__ import annotations

import re

from loguru import logger

from app.gateway.pii import mask

SURNAMES = (
    "nguyễn trần lê phạm hoàng huỳnh phan vũ võ đặng bùi đỗ hồ ngô dương lý đinh trịnh "
    "lâm mai tô tạ cao lương la đoàn vương trương kiều châu quách hà thái tăng lục"
).split()
_HONORIFIC = r"anh|chị|em|ông|bà|cô|chú|bác|thầy|bạn|luật sư|ls|tên là|tôi là|mình là"
_SYL = r"[a-zàáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]+"
_SURNAME = "|".join(SURNAMES)
_END = r"(?=[\s,.?!]|$)"
# "anh nguyễn văn an", "luật sư đỗ đăng khoa": họ + 1–3 âm tiết sau xưng hô
_NAME_AFTER = re.compile(
    rf"(?<!\w)(?P<prefix>(?:{_HONORIFIC})\s+)(?P<value>(?:{_SURNAME})(?:\s+{_SYL}){{1,3}}){_END}",
    re.IGNORECASE,
)
# tên hiển thị kiểu mạng xã hội sau lời chào: "chào bạn bảy bảy nguyễn", "bạn lan phạm"
_NAME_BEFORE_SURNAME = re.compile(
    rf"(?<!\w)(?P<prefix>(?:chào bạn|chào anh|chào chị|của bạn)\s+)"
    rf"(?P<value>{_SYL}(?:\s+{_SYL})?\s+(?:{_SURNAME})){_END}",
    re.IGNORECASE,
)
_DIGIT = r"không|một|mốt|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|linh|lẻ"
# từ 7 chữ số đọc liền trở lên: số điện thoại, số tài khoản, CCCD đọc thành chữ
_SPOKEN_NUMBER = re.compile(
    rf"(?<!\w)(?:(?:{_DIGIT})[\s,.-]+){{6,}}(?:{_DIGIT})(?!\w)", re.IGNORECASE
)
_ADDRESS_WORD = re.compile(
    r"(?<!\w)(?:số|đường|phố|ngõ|ngách|hẻm|kiệt|thôn|xóm|ấp|tổ|khu phố)(?!\w)", re.IGNORECASE
)
TYPES = {"TÊN", "TỔ_CHỨC", "SĐT", "STK", "ĐỊA_CHỈ"}
_GENERIC_ORG = set(
    "văn phòng công chứng ty luật tòa toà án ủy uỷ ban nhân dân cơ quan thuế bảo hiểm xã hội "
    "ngân hàng doanh nghiệp đơn vị bộ phận kế toán nhân sự kênh trung tâm sở phòng chi cục "
    "nhà nước chính phủ của các một bất động sản tư vấn đầu tư thương mại dịch vụ xây dựng "
    "tnhh cổ phần hãng tập đoàn pháp truyền hình báo đài tạp chí kinh tế tài chính ứng dụng "
    "livestream live stream tư vấn giải đáp".split()
)

NER_SYSTEM = """Bạn tìm dữ liệu cá nhân trong một đoạn bản chép lời tiếng Việt (chữ thường, \
không dấu câu). Chỉ trả về JSON, ví dụ:
{"items": [{"type": "TÊN", "text": "nguyễn văn an"},
 {"type": "TỔ_CHỨC", "text": "công ty luật abc"}]}
"type" là MỘT trong: TÊN, TỔ_CHỨC, SĐT, STK, ĐỊA_CHỈ.
- "text" chép NGUYÊN VĂN đúng như trong đoạn (cùng chữ thường, cùng chính tả).
- TÊN: tên người thật (người hỏi, người được nhắc, người dẫn chương trình, luật sư).
- TỔ_CHỨC: tên công ty, văn phòng luật tư nhân; KHÔNG lấy cơ quan nhà nước, toà án, \
tên luật, tên đài báo.
- ĐỊA_CHỈ: số nhà, tên đường, thôn/xóm; KHÔNG lấy tên tỉnh/thành phố đứng một mình.
- SĐT/STK: chỉ dãy số điện thoại, số tài khoản; KHÔNG lấy diện tích, số tiền, ngày tháng.
- Không có thì trả {"items": []}."""


def _plausible(etype: str, value: str) -> bool:
    """Bỏ nhãn sai hay gặp của mô hình 7B: diện tích/số tiền bị gọi là STK, v.v."""
    if etype in {"SĐT", "STK"}:
        return bool(_SPOKEN_NUMBER.search(value) or re.search(r"\d{7,}", value))
    if etype == "ĐỊA_CHỈ":
        return bool(_ADDRESS_WORD.search(value))
    if etype == "TỔ_CHỨC":  # "văn phòng công chứng" là danh từ chung, không phải tên riêng
        return any(w not in _GENERIC_ORG for w in value.lower().split())
    return etype in TYPES


def _new_placeholder(mapping: dict[str, str], etype: str, value: str) -> str:
    for ph, v in mapping.items():
        if v.lower() == value.lower():
            return ph
    n = 1 + sum(1 for k in mapping if k.startswith(f"[{etype}_"))
    ph = f"[{etype}_{n}]"
    mapping[ph] = value
    return ph


def _rule(pattern: re.Pattern[str], etype: str, text: str, mapping: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        grouped = "value" in m.groupdict()
        value = (m.group("value") if grouped else m.group(0)).strip()
        ph = _new_placeholder(mapping, etype, value)
        return m.group("prefix") + ph if grouped else ph

    return pattern.sub(repl, text)


def replace_known(text: str, mapping: dict[str, str]) -> str:
    """Thay MỌI lần xuất hiện của giá trị đã biết (giá trị dài thay trước).

    Khoảng trắng trong giá trị khớp cả xuống dòng (tên công ty vắt qua hai đoạn). Tên một
    âm tiết ("phương") chỉ thay khi đứng sau xưng hô, để "đối phương" không bị che.
    """
    for ph, value in sorted(mapping.items(), key=lambda kv: -len(kv[1])):
        words = value.split()
        if len(value) < 3 or not words:
            continue
        body = r"\s+".join(re.escape(w) for w in words)
        if len(words) == 1:
            text = re.sub(rf"(?<!\w)((?:{_HONORIFIC})\s+){body}(?!\w)",
                          lambda m, ph=ph: m.group(1) + ph, text, flags=re.IGNORECASE)
        else:
            text = re.sub(rf"(?<!\w){body}(?!\w)", ph, text, flags=re.IGNORECASE)
    return text


def ner_values(router, text: str) -> list[tuple[str, str]]:
    """Mô hình trong máy (mức A) liệt kê PII; lỗi thì trả [] và chỉ dựa vào luật."""
    from app.llm.context import data_class_scope
    from app.llm.router import parse_json

    try:
        with data_class_scope("A"):
            raw = router.chat(
                [{"role": "system", "content": NER_SYSTEM}, {"role": "user", "content": text}],
                task="route", temperature=0.0,
            ).text
        items = parse_json(raw).get("items") or []
    except Exception as exc:  # noqa: BLE001 — thiếu lớp NER vẫn còn các lớp luật
        logger.warning("NER che PII lỗi: {}", exc)
        return []
    out = []
    for it in items:
        if not (isinstance(it, dict) and isinstance(it.get("text"), str)):
            continue
        value = it["text"].strip()
        etype = str(it.get("type") or "TÊN").upper().replace(" ", "_").split("|")[0]
        if len(value) >= 3 and value.lower() in text.lower() and _plausible(etype, value):
            out.append((etype, value))
    return out


def _given_names(text: str, mapping: dict[str, str]) -> str:
    """Tên gọi sau xưng hô ("thầy khoa") của người đã che dùng chung placeholder."""
    for ph, value in list(mapping.items()):
        parts = value.split()
        if not ph.startswith("[TÊN_") or len(parts) < 2 or len(parts[-1]) < 2:
            continue
        text = re.sub(
            rf"(?<!\w)((?:{_HONORIFIC})\s+){re.escape(parts[-1])}(?!\w)",
            lambda m, ph=ph: m.group(1) + ph, text, flags=re.IGNORECASE,
        )
    return text


def add_ner(router, text: str, mapping: dict[str, str]) -> None:
    """Đưa giá trị NER của một cửa sổ văn bản vào ánh xạ (chưa thay gì trong văn bản)."""
    for etype, value in ner_values(router, text):
        _new_placeholder(mapping, etype, value)
        if etype == "TỔ_CHỨC":
            # phần riêng của tên ("hân vượng") vẫn bị che khi tên vắt qua hai đoạn chép lời
            words = value.split()
            core = [w for w in words if w.lower() not in _GENERIC_ORG]
            if len(core) >= 2 and len(core) < len(words):
                _new_placeholder(mapping, etype, " ".join(core))


def mask_spoken(text: str, *, mapping: dict[str, str], router=None) -> str:
    """Che một đoạn chép lời; `mapping` dùng chung cho cả tệp và được mở rộng tại chỗ."""
    if router is not None:
        add_ner(router, text, mapping)
    out = replace_known(text, mapping)
    out = mask(out, mapping=mapping).text
    out = _rule(_NAME_AFTER, "TÊN", out, mapping)
    out = _rule(_NAME_BEFORE_SURNAME, "TÊN", out, mapping)
    out = _rule(_SPOKEN_NUMBER, "SỐ", out, mapping)
    out = replace_known(out, mapping)
    return _given_names(out, mapping)
