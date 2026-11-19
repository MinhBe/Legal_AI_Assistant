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
    rf"(?<!\w)(?P<prefix>(?:{_HONORIFIC})\s+)(?P<value>(?:{_SURNAME})(?:[ ]+{_SYL}){{1,3}}){_END}",
    re.IGNORECASE,
)
# tên hiển thị kiểu mạng xã hội sau lời chào: "chào bạn bảy bảy nguyễn", "bạn lan phạm"
_NAME_BEFORE_SURNAME = re.compile(
    rf"(?<!\w)(?P<prefix>(?:chào bạn|chào anh|chào chị|của bạn)\s+)"
    rf"(?P<value>{_SYL}(?:[ ]+{_SYL})?[ ]+(?:{_SURNAME})){_END}",
    re.IGNORECASE,
)
_DIGIT = r"không|một|mốt|hai|ba|bốn|tư|năm|lăm|sáu|bảy|tám|chín|linh|lẻ"
# từ 7 chữ số đọc liền trở lên: số điện thoại, số tài khoản, CCCD đọc thành chữ
_SPOKEN_NUMBER = re.compile(
    rf"(?<!\w)(?:(?:{_DIGIT})[ ,.-]+){{6,}}(?:{_DIGIT})(?!\w)", re.IGNORECASE
)
_ADDRESS_WORD = re.compile(
    r"(?<!\w)(?:số|đường|phố|ngõ|ngách|hẻm|kiệt|thôn|xóm|ấp|tổ|khu phố)(?!\w)", re.IGNORECASE
)
TYPES = {"TÊN", "TỔ_CHỨC", "SĐT", "STK", "ĐỊA_CHỈ"}
# doanh nghiệp / văn phòng luật tư nhân: chỉ những tổ chức này mới bị che
_PRIVATE_ORG = re.compile(
    r"^(?:công ty|cty|văn phòng luật|văn phòng luật sư|hãng luật|doanh nghiệp|tập đoàn|"
    r"cửa hàng|cơ sở|hộ kinh doanh|kênh của)\b", re.IGNORECASE)
# địa danh hành chính: không phải dữ liệu cá nhân, và là tình tiết (diện tích tối thiểu theo tỉnh)
_PLACE = re.compile(
    r"^(?:thành phố|tp|tỉnh|huyện|quận|thị xã|xã|phường|thị trấn|hà nội|sài gòn|"
    r"hồ chí minh|đà nẵng|hải phòng|cần thơ|huế)\b", re.IGNORECASE)
# quan hệ gia đình / xưng hô: NER 7B hay gán nhầm thành TÊN ("cha mẹ", "con nuôi")
_KIN = set(
    "bố mẹ cha má ba con cháu chắt anh chị em ông bà vợ chồng cô chú bác dì dượng thím mợ cậu "
    "trai gái nuôi đẻ riêng chung ruột dâu rể họ hàng người bạn thầy luật sư khách".split()
)
# Cơ quan, ứng dụng công, tên văn bản: không phải dữ liệu cá nhân, che đi thì mất nghĩa pháp lý
_PUBLIC = re.compile(
    r"^(?:e-?tax|i ?tách|ứng dụng e|cơ quan|tổng cục|cục thuế|chi cục|vtv|htv|"
    r"to[àa] án|viện kiểm sát|công an|ubnd|[uủ]y ban|văn phòng công chứng|"
    r"văn phòng đăng ký|bộ luật|luật\s|nghị định|thông tư|quốc hội|chính phủ)",
    re.IGNORECASE,
)
# Tên gọi đứng một mình sau lời giới thiệu: "của bạn là minh", "tên là lan", "chào bạn hùng"
_NOT_NAME = set(
    "ai gì gi người một hai ba đây đó đấy thế như này kia là có không được và thì mà ạ nhé nha "
    "nhá ơi à ừ vâng dạ ok tôi mình em anh chị bạn các những cái về câu hỏi "
    "ấy nào khác thường hay cũng đã đang sẽ muốn đều vẫn mới lại còn nữa chỉ cứ rất "
    "nhiều ít tự hãy đừng thì là xin cho".split()
)
_BARE_NAME = re.compile(
    rf"(?<!\w)(?P<prefix>(?:của bạn là|tên là|tên tôi là|tên mình là|chào bạn|chào anh|chào chị)"
    rf"\s+)(?P<value>{_SYL})(?!\w)",
    re.IGNORECASE,
)
# người hỏi trên livestream: "bạn tùng hỏi", "bạn trường có hỏi", "bạn là thúy hỏi",
# "câu hỏi tiếp của bạn phùng là" (đo trên tệp 1, 18/11/2026)
_ASKER = re.compile(
    rf"(?<!\w)(?P<prefix>bạn(?:[ ]+là)?[ ]+)(?P<value>{_SYL}(?:[ ]+{_SYL}){{0,2}})"
    rf"(?=[ ]+(?:có[ ]+)?(?:hỏi|thắc mắc|bình luận)\b)",
    re.IGNORECASE,
)
_ASKER_OF = re.compile(
    rf"(?<!\w)(?P<prefix>(?:câu hỏi|thắc mắc)(?:[ ]+tiếp(?:[ ]+theo)?)?[ ]+của[ ]+bạn[ ]+)"
    rf"(?P<value>{_SYL}(?:[ ]+{_SYL})?)(?=[ ]+(?:là|đó là|hỏi)\b)",
    re.IGNORECASE,
)
# bản chép có chữ hoa (Whisper): "bạn Minh", "bạn Lan Anh"
# chỉ chữ HOA (dải "À-Ỹ" của Unicode lẫn cả chữ thường như "đ", "ã" nên không dùng được)
_UPPER = "A-ZĂÂĐÊÔƠƯÀÁẢÃẠẰẮẲẴẶẦẤẨẪẬÈÉẺẼẸỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌỒỐỔỖỘỜỚỞỠỢÙÚỦŨỤỪỨỬỮỰỲÝỶỸỴ"
_CAP = rf"[{_UPPER}][a-zàáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]+"
_CAP_NAME = re.compile(
    rf"(?<!\w)(?P<prefix>(?:[Bb]ạn|[Cc]hào)[ ]+)(?P<value>{_CAP}(?:[ ]+{_CAP})?)(?!\w)"
)
# số CCCD/CMND viết liền (số tiền có dấu chấm phân cách thì không bị bắt)
_ID_NUMBER = re.compile(r"(?<![\d.,])(?:\d{9}|\d{12})(?![\d.,])")
_KEEP = frozenset({"TIỀN", "CCCD"})  # số tiền là tình tiết; CCCD dùng luật riêng ở trên
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
    words = value.lower().split()
    if _PUBLIC.match(value.strip()) or _PLACE.match(value.strip()):
        return False
    if etype == "TỔ_CHỨC":
        # chỉ tên doanh nghiệp/văn phòng luật TƯ NHÂN mới là dữ liệu nhận diện; NER 7B hay gán
        # nhầm "đất đai", "trợ lý", tên đài báo, tên thành phố (đo trên tệp 1, 18/11/2026)
        return bool(_PRIVATE_ORG.match(value.strip())) and any(
            w not in _GENERIC_ORG for w in words)
    if etype == "TÊN":  # "cha mẹ", "con nuôi", "anh", "bảy có" không phải tên người
        return (words[0] not in _KIN | _NOT_NAME and words[-1] not in _NOT_NAME
                and not all(w in _KIN | _NOT_NAME for w in words))
    return etype in TYPES


def _new_placeholder(mapping: dict[str, str], etype: str, value: str) -> str:
    for ph, v in mapping.items():
        if v.lower() == value.lower():
            return ph
    # số thứ tự = lớn nhất + 1 (không phải đếm + 1): ánh xạ đã lọc có thể có lỗ, đếm thì trùng
    # số và GHI ĐÈ giá trị cũ -> các dòng sau không còn che giá trị đó nữa
    used = [int(k[len(etype) + 2:-1]) for k in mapping
            if k.startswith(f"[{etype}_") and k[len(etype) + 2:-1].isdigit()]
    ph = f"[{etype}_{max(used, default=0) + 1}]"
    mapping[ph] = value
    return ph


def _rule(pattern: re.Pattern[str], etype: str, text: str, mapping: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        grouped = "value" in m.groupdict()
        value = (m.group("value") if grouped else m.group(0)).strip()
        ph = _new_placeholder(mapping, etype, value)
        return m.group("prefix") + ph if grouped else ph

    return pattern.sub(repl, text)


def _named(pattern: re.Pattern[str], text: str, mapping: dict[str, str]) -> str:
    """Tên đứng một mình: bỏ qua từ thường ("chào bạn nhé") và tên cơ quan công."""
    def repl(m: re.Match[str]) -> str:
        words = m.group("value").split()
        lead = []  # từ đệm đứng trước tên ("bạn à am hỏi") giữ nguyên, phần sau mới là tên
        while words and words[0].lower() in _NOT_NAME:
            lead.append(words.pop(0))
        tail = []  # "bạn trường có hỏi": "có" là từ đệm, không thuộc tên
        while words and words[-1].lower() in _NOT_NAME:
            tail.insert(0, words.pop())
        value = " ".join(words)
        if not value or _PUBLIC.match(value) or words[0].lower() in _KIN:
            return m.group(0)
        head = m.group("prefix") + (" ".join(lead) + " " if lead else "")
        after = " " + " ".join(tail) if tail else ""
        return head + _new_placeholder(mapping, "TÊN", value) + after

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
        else:  # giữ nguyên số dòng để tách lại đúng từng đoạn chép lời
            text = re.sub(rf"(?<!\w){body}(?!\w)",
                          lambda m, ph=ph: ph + "\n" * m.group(0).count("\n"),
                          text, flags=re.IGNORECASE)
    return text


_ITEM = re.compile(r'\{[^{}]*?"text"\s*:\s*"(?P<text>[^"\\]+)"[^{}]*?\}')
_TYPE = re.compile(r'"type"\s*:\s*"(?P<type>[^"\\]+)"')


def salvage_items(raw: str) -> list[dict]:
    """Các mục {"text":…, "type":…} hoàn chỉnh trong một chuỗi JSON hỏng hoặc bị cắt."""
    out = []
    for m in _ITEM.finditer(raw or ""):
        t = _TYPE.search(m.group(0))
        out.append({"text": m.group("text"), "type": t.group("type") if t else "TÊN"})
    return out


def ner_values(router, text: str) -> list[tuple[str, str]]:
    """Mô hình trong máy (mức A) liệt kê PII; lỗi thì trả [] và chỉ dựa vào luật."""
    from app.llm.context import data_class_scope
    from app.llm.router import parse_json

    raw = ""
    try:
        with data_class_scope("A"):
            raw = router.chat(
                [{"role": "system", "content": NER_SYSTEM}, {"role": "user", "content": text}],
                task="route", temperature=0.0,
            ).text
        items = parse_json(raw).get("items") or []
    except Exception as exc:  # noqa: BLE001 — thiếu lớp NER vẫn còn các lớp luật
        items = salvage_items(raw)  # JSON bị cắt giữa chừng (hết max_new_tokens): lấy các mục đủ
        logger.warning("NER che PII lỗi: {} (cứu được {} mục)", exc, len(items))
        if not items:
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
        if (not ph.startswith("[TÊN_") or len(parts) < 2 or len(parts[-1]) < 2
                or parts[-1].lower() in _NOT_NAME | _KIN):
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
            # phần riêng chỉ lấy khi không phải từ chung/địa danh ("đất đai", "sài gòn")
            # chỉ với tên dài ("công ty luật bất động sản hưng vượng"); "công ty thanh lý" mà
            # tách lõi thì "thanh lý (hợp đồng)" bị che khắp nơi
            if (len(words) >= 4 and len(core) >= 2 and len(core) < len(words)
                    and not _PLACE.match(" ".join(core)) and _plausible("TÊN", " ".join(core))):
                _new_placeholder(mapping, etype, " ".join(core))


def mask_spoken(text: str, *, mapping: dict[str, str], router=None) -> str:
    """Che một đoạn chép lời; `mapping` dùng chung cho cả tệp và được mở rộng tại chỗ."""
    if router is not None:
        add_ner(router, text, mapping)
    out = replace_known(text, mapping)
    # luật cũ có \s+ bên trong giá trị: chạy từng dòng để không nuốt mất dấu xuống dòng
    out = "\n".join(mask(line, mapping=mapping, skip=_KEEP).text for line in out.split("\n"))
    out = _rule(_ID_NUMBER, "CCCD", out, mapping)
    out = _rule(_NAME_AFTER, "TÊN", out, mapping)
    out = _rule(_NAME_BEFORE_SURNAME, "TÊN", out, mapping)
    out = _named(_BARE_NAME, out, mapping)
    out = _named(_ASKER, out, mapping)
    out = _named(_ASKER_OF, out, mapping)
    out = _named(_CAP_NAME, out, mapping)
    out = _rule(_SPOKEN_NUMBER, "SỐ", out, mapping)
    out = replace_known(out, mapping)
    return _given_names(out, mapping)


def mask_lines(lines: list[str], *, mapping: dict[str, str], router=None) -> list[str]:
    """Che cả cửa sổ một lượt rồi tách lại từng đoạn: ngữ cảnh vắt qua ranh giới đoạn
    ("…của bạn là" | "Minh đó là…") vẫn được nhận ra. Mỗi đoạn không được chứa xuống dòng."""
    lines = [line.replace("\n", " ") for line in lines]
    out = mask_spoken("\n".join(lines), mapping=mapping, router=router).split("\n")
    if len(out) != len(lines):  # không bao giờ được xảy ra; vẫn che được, chỉ mất ngữ cảnh
        logger.warning("mask_lines: lệch số dòng, che từng đoạn")
        out = [mask_spoken(line, mapping=mapping) for line in lines]
    return [replace_known(line, mapping) for line in out]
