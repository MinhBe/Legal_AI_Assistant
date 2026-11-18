"""Che dữ liệu cá nhân trước khi câu hỏi tới LLM bên ngoài (design §4, contract G1).

Ánh xạ placeholder -> giá trị gốc chỉ sống trong tiến trình này: không ghi log,
không trả về client. `unmask` khôi phục đúng chuỗi gốc của lần che đầu tiên.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Tên loại = nhãn trong placeholder, cũng là khoá của `counts`.
EMAIL, TIEN, STK, CCCD, SDT, TEN, DIACHI = (
    "EMAIL", "TIỀN", "STK", "CCCD", "SĐT", "TÊN", "ĐỊA_CHỈ",
)


@dataclass
class Masked:
    text: str                   # văn bản đã che
    mapping: dict[str, str]     # placeholder -> giá trị gốc (chỉ trong bộ nhớ)
    counts: dict[str, int]      # loại thực thể -> số giá trị khác nhau


_RE_PLACEHOLDER = re.compile(r"^\[(.+)_(\d+)\]$")
_RE_KEY = re.compile(r"[\s.\-]+")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# tiền: số có dấu phân cách + đơn vị tiền, hoặc số + "triệu/tỷ" (đã là tiền)
_NUM = r"\d{1,3}(?:[.,]\d{3})*(?:[.,]\d+)?|\d+"
_TIEN_RE = re.compile(
    rf"(?<![\d.,])(?:{_NUM})\s*(?:triệu|tỷ|tỉ|nghìn|ngàn)?\s*(?:đồng|vnđ|vnd|đ)\b"
    rf"|(?<![\d.,])(?:{_NUM})\s*(?:triệu|tỷ|tỉ)\b"
    rf"|(?:vnđ|vnd)\s*(?:{_NUM})(?!\d)",
    re.IGNORECASE,
)

# số tài khoản: chỉ nhận khi có chữ dẫn ngay trước
_STK_RE = re.compile(
    r"(?P<prefix>(?:STK|số\s+tài\s+khoản|tài\s+khoản\s+số|TK)\s*[:.]?\s*)"
    r"(?P<value>\d[\d .-]{4,28}\d)",
    re.IGNORECASE,
)

# CCCD 12 số / CMND 9 số, viết liền hoặc nhóm 3 số
_CCCD_RE = re.compile(r"(?<![\d.,])(?:\d{9}|\d{12}|\d{3}(?:[ .]\d{3}){2,3})(?!\d)")

# điện thoại VN: 0 / 84 / +84 rồi 9 số
_SDT_RE = re.compile(r"(?<!\d)(?:\+84|84|0)(?:[ .-]?\d){9}(?!\d)")

_SYL = r"[A-ZĐ][a-zàáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]+"
_TEN_RE = re.compile(
    r"(?<![\w])(?P<prefix>(?:(?i:họ\s+và\s+tên|họ\s+tên|người\s+lao\s+động|tên\s+tôi\s+là"
    r"|tôi\s+là|ông|bà|anh|chị|em|cô|chú|Mr|Mrs|Ms))\s*:?\s+)"
    rf"(?P<value>{_SYL}(?:\s+{_SYL}){{0,3}})(?![\w])"
)
# chữ hoa đầu câu / từ chung hay đứng sau "ông", "bà" trong văn bản luật
_TEN_STOP = {
    "Công", "Tòa", "Toà", "Nhà", "Bộ", "Điều", "Khoản", "Luật", "Người", "Theo",
    "Nếu", "Trường", "Chính", "Ban", "Tổng", "Ủy", "Uỷ", "Việt", "Hà",
}

_DIACHI_RE = re.compile(
    r"(?P<prefix>(?i:địa\s+chỉ|trú\s+tại|thường\s+trú|cư\s+trú\s+tại|ở\s+số)\s*:?\s+)"
    r"(?P<value>[^;\n.]{5,120})"
)


def _looks_like_address(value: str) -> bool:
    """Địa chỉ thật có số nhà; "cư trú tại Việt Nam" trong luật thì không."""
    return bool(re.search(r"\d", value))


# Thứ tự quan trọng: tiền và số tài khoản che trước để dãy số của chúng không bị
# nhận nhầm thành CCCD/điện thoại, tên che trước địa chỉ để tên trong địa chỉ không lọt.
_RULES: list[tuple[str, re.Pattern[str], object]] = [
    (EMAIL, _EMAIL_RE, None),
    (STK, _STK_RE, None),
    (TIEN, _TIEN_RE, None),
    (CCCD, _CCCD_RE, None),
    (SDT, _SDT_RE, None),
    (TEN, _TEN_RE, lambda v: v.split()[0] not in _TEN_STOP),
    (DIACHI, _DIACHI_RE, _looks_like_address),
]


def _next_index(mapping: dict[str, str], etype: str) -> int:
    top = 0
    for key in mapping:
        m = _RE_PLACEHOLDER.match(key)
        if m and m.group(1) == etype:
            top = max(top, int(m.group(2)))
    return top + 1


def mask(
    text: str, *, mapping: dict[str, str] | None = None, skip: frozenset[str] = frozenset()
) -> Masked:
    """Che PII trong `text`. `mapping` (nếu có) được mở rộng tại chỗ, để lượt sau
    dùng lại đúng placeholder của lượt trước (lịch sử hội thoại). `skip` là các loại
    không che (bản chép lời giữ số tiền vì đó là tình tiết pháp lý)."""
    mapping = mapping if mapping is not None else {}
    reverse = {v: k for k, v in mapping.items()}
    seen: dict[str, set[str]] = {}
    out = text

    for etype, pattern, check in _RULES:
        if etype in skip:
            continue
        def repl(m: re.Match[str], etype: str = etype, check: object = check) -> str:
            grouped = "value" in m.groupdict()
            value = m.group("value") if grouped else m.group(0)
            if check is not None and not check(value):  # type: ignore[operator]
                return m.group(0)
            key = _RE_KEY.sub("", value).lower()
            placeholder = reverse.get(key)
            if placeholder is None:
                placeholder = f"[{etype}_{_next_index(mapping, etype)}]"
                mapping[placeholder] = value
                reverse[key] = placeholder
            seen.setdefault(etype, set()).add(key)
            if grouped:
                at = m.start("value") - m.start()
                whole = m.group(0)
                return whole[:at] + placeholder + whole[at + len(value):]
            return placeholder

        out = pattern.sub(repl, out)

    return Masked(text=out, mapping=mapping, counts={k: len(v) for k, v in seen.items()})


def unmask(text: str, mapping: dict[str, str]) -> str:
    """Khôi phục giá trị gốc. Placeholder dài thay trước để `[TÊN_1]` không cắt
    của `[TÊN_10]`."""
    for placeholder in sorted(mapping, key=len, reverse=True):
        text = text.replace(placeholder, mapping[placeholder])
    return text
