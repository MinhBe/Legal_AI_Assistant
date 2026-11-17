"""Bộ lọc cặp hỏi–đáp sinh ra (KG1) — thuần code, không gọi mô hình.

Giữ một cặp chỉ khi: mọi trích dẫn "Điều X khoản Y {văn bản} ({mốc hiệu lực})" có thật
trong kho, mốc hiệu lực đúng với văn bản, câu trả lời có dấu tiếng Việt, độ dài hợp lý
và không gần trùng câu hỏi đã giữ.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.rag.embeddings import embed

Q_MIN, Q_MAX = 20, 600
A_MIN, A_MAX = 80, 2500
DIACRITIC_MIN = 0.05
DUP_COSINE = 0.95

# "Điều 35 khoản 2 BLLĐ 2019 (hiệu lực từ 01/01/2021)"
CITE = re.compile(
    r"Điều\s+(?P<article>\d+)(?:\s+khoản\s+(?P<clause>\d+))?\s+"
    r"(?P<doc>[^()\n.;,]{2,40}?)\s*\((?P<tag>[^()\n]{5,80})\)"
)
# Án lệ không phải điều luật: cặp chỉ trích "Án lệ số …" vẫn hợp lệ (KG1).
PRECEDENT_CITE = re.compile(r"Án lệ số\s+\d+")
_DIA = re.compile(
    "[ăâđêôơưàáảãạằắẳẵặầấẩẫậèéẻẽẹềếểễệìíỉĩịòóỏõọồốổỗộờớởỡợùúủũụừứửữựỳýỷỹỵ]",
    re.IGNORECASE,
)


def diacritic_ratio(text: str) -> float:
    """Tỉ lệ ký tự có dấu tiếng Việt — câu trả lời không dấu là dấu hiệu văn bản rác."""
    return len(_DIA.findall(text)) / max(1, len(text))


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class PairIndex:
    """Khoá trích dẫn hợp lệ + câu đã giữ, để lọc từng cặp sinh ra.

    `records` là bản ghi luật (`doc_label`, `article_no`, `clause_no`, `time_tag`) —
    toàn bộ kho, không chỉ phần đang sinh, để cặp "bẫy thời gian" vẫn đối chiếu được.
    """

    def __init__(
        self,
        records: list[dict],
        embed_fn: Callable[[list[str]], list[list[float]]] = embed,
    ) -> None:
        self.articles: set[tuple[str, int, int | None]] = set()
        self.tags: dict[str, set[str]] = {}
        for r in records:
            if not r.get("doc_label") or r.get("article_no") is None:
                continue
            self.articles.add((r["doc_label"], r["article_no"], r.get("clause_no")))
            self.tags.setdefault(r["doc_label"], set()).add(r["time_tag"])
        self.embed_fn = embed_fn
        self.kept: list[list[float]] = []

    def check(self, question: str, answer: str, source_text: str | None = None) -> str | None:
        """Trả lý do loại, hoặc None nếu cặp đạt mọi điều kiện."""
        if not Q_MIN <= len(question.strip()) <= Q_MAX:
            return "length_question"
        if not A_MIN <= len(answer) <= A_MAX:
            return "length_answer"
        if diacritic_ratio(answer) < DIACRITIC_MIN:
            return "no_diacritics"
        cites = list(CITE.finditer(answer))
        if not cites and not PRECEDENT_CITE.search(answer):
            return "no_citation"
        for m in cites:
            doc = m["doc"].strip()
            article = int(m["article"])
            clause = int(m["clause"]) if m["clause"] else None
            if (doc, article, clause) not in self.articles:
                return "cited_missing"
            if f"{doc} ({m['tag'].strip()})" not in self.tags.get(doc, set()):
                return "time_tag"
        # sau khi trích dẫn đã hợp lệ mới xét thời điểm câu hỏi và độ bám nội dung
        why = _time_and_grounding(question, answer, source_text)
        if why:
            return why
        if self.kept:
            vec = self.embed_fn([question])[0]
            if any(cosine(vec, k) >= DUP_COSINE for k in self.kept):
                return "near_duplicate"
        return None

    def add(self, question: str) -> None:
        self.kept.append(self.embed_fn([question])[0])


GROUNDING_MIN = 0.25  # phần cặp từ (bigram) của điều luật nguồn phải xuất hiện trong câu trả lời
_EXPIRED = re.compile(r"hết hiệu lực từ\s+(\d{2})/(\d{2})/(\d{4})")
_WORD = re.compile(r"\w+", re.UNICODE)


def _bigrams(text: str) -> set[tuple[str, str]]:
    words = [w.lower() for w in _WORD.findall(text) if not w.isdigit() and len(w) > 1]
    return set(zip(words, words[1:], strict=False))


def grounding(answer: str, source_text: str) -> float:
    """Tỉ lệ cặp từ của nguồn có trong câu trả lời: trả lời chung chung thì thấp."""
    src = _bigrams(source_text)
    return len(src & _bigrams(answer)) / len(src) if src else 1.0


def _time_and_grounding(question: str, answer: str, source_text: str | None) -> str | None:
    """Hai lỗi bộ lọc cũ để lọt (đo trên lô thử 17/11/2026):
    - trích luật đã hết hiệu lực cho câu hỏi kiểu chuyện hiện nay → model học trích luật cũ;
    - câu trả lời chung chung không nêu nội dung điều luật."""
    from datetime import date

    from app.amend.timeframe import extract_event_date

    for m in _EXPIRED.finditer(answer):
        expiry = date(int(m[3]), int(m[2]), int(m[1]))
        event, _gran = extract_event_date(question, date.today())
        if event is None or event >= expiry:
            return "repealed_without_past_date"
    if source_text and len(source_text) >= 200 and grounding(answer, source_text) < GROUNDING_MIN:
        return "not_grounded"
    return None


def check_pair(
    pair: dict,
    index: PairIndex,
    source_text: str | None = None,
) -> str | None:
    """Lọc một cặp `{"question", "answer"}` bằng `index`; đạt thì ghi câu hỏi vào index."""
    why = index.check(pair["question"], pair["answer"], source_text)
    if why is None:
        index.add(pair["question"])
    return why
