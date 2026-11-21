"""De-identification at the door.

The default masker is a light Vietnamese rule set. It is deliberately replaceable:
a product (LawVN) passes its own stronger masker (gateway G1) and the pipeline
uses that instead. The contract is the `Masker` protocol: `mask(text) -> text`.

Consistency matters for legal text, so the same original maps to the same
pseudonym within one masker instance (Nguyễn Văn B, Công ty X, [SĐT-1]).
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable


@runtime_checkable
class Masker(Protocol):
    def mask(self, text: str) -> str: ...


# Longer / more specific IDs are masked before phones so a 12-digit căn cước is
# never mis-read as a phone number.
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_CCCD = re.compile(r"(?<!\d)\d{12}(?!\d)")  # căn cước 12 digits
_CMND = re.compile(r"(?<!\d)\d{9}(?!\d)")  # chứng minh nhân dân 9 digits
_PHONE = re.compile(r"(?<!\d)(?:\+?84|0)\d{9,10}(?!\d)")  # VN mobile/landline
# A Vietnamese full name: 2-4 capitalised (incl. diacritic) words. Trigger only
# after a cue word (case-insensitive) so we do not mask every capitalised phrase.
_NAME_CUE = re.compile(
    r"\b(?i:ông|bà|anh|chị|em|cháu|ngài|cô|chú|bác|họ tên|tên là|người lao động|"
    r"người sử dụng lao động|nguyên đơn|bị đơn)\s+"
    r"([A-ZÀ-Ỹ][a-zà-ỹ]+(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]+){1,3})",
    re.UNICODE,
)
_COMPANY = re.compile(
    r"\b(?:Công ty|Cty|Doanh nghiệp|Tập đoàn)\b(?:\s+(?:TNHH|Cổ phần|CP|MTV))?"
    r"\s+([A-ZÀ-Ỹ0-9][\wÀ-ỹ]*(?:\s+[A-ZÀ-Ỹ0-9][\wÀ-ỹ]*){0,4})",
    re.UNICODE,
)


class VietnamesePiiMasker:
    """Light, consistent masking. Not a guarantee; a product should layer its own."""

    def __init__(self) -> None:
        self._seq: dict[str, str] = {}
        self._name_letters = iter("BCDEFGHKLMNPQRST")
        self._company_letters = iter("XYZABCDEFGHKLMN")
        self._counters: dict[str, int] = {}

    def _pseudonym_name(self, original: str) -> str:
        if original not in self._seq:
            try:
                letter = next(self._name_letters)
            except StopIteration:
                letter = "N"
            self._seq[original] = f"Nguyễn Văn {letter}"
        return self._seq[original]

    def _pseudonym_company(self, original: str) -> str:
        if original not in self._seq:
            try:
                letter = next(self._company_letters)
            except StopIteration:
                letter = "X"
            self._seq[original] = f"Công ty {letter}"
        return self._seq[original]

    def _tag(self, kind: str, original: str) -> str:
        if original not in self._seq:
            self._counters[kind] = self._counters.get(kind, 0) + 1
            self._seq[original] = f"[{kind}-{self._counters[kind]}]"
        return self._seq[original]

    def mask(self, text: str) -> str:
        if not text:
            return text

        def repl_company(m: re.Match) -> str:
            return self._pseudonym_company(m.group(0))

        def repl_name(m: re.Match) -> str:
            cue = m.group(0)[: m.start(1) - m.start(0)]
            return cue + self._pseudonym_name(m.group(1))

        text = _COMPANY.sub(repl_company, text)
        text = _NAME_CUE.sub(repl_name, text)
        text = _EMAIL.sub(lambda m: self._tag("EMAIL", m.group(0)), text)
        text = _CCCD.sub(lambda m: self._tag("CCCD", m.group(0)), text)
        text = _CMND.sub(lambda m: self._tag("CMND", m.group(0)), text)
        text = _PHONE.sub(lambda m: self._tag("SĐT", m.group(0)), text)
        return text
