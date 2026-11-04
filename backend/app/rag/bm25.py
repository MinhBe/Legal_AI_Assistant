"""BM25 trong bộ nhớ trên legal_node.

Kho khoảng 3.000 node nên chấm điểm toàn kho mỗi câu hỏi chỉ mất vài mili giây.
Tách từ underthesea cho cả kho mất vài chục giây, nên chỉ mục được lưu vào
data/cache và chỉ dựng lại khi số node hoặc tham số đổi.
"""

from __future__ import annotations

import math
import pickle
import threading
from collections import Counter, defaultdict
from pathlib import Path

from loguru import logger
from sqlalchemy import text

from app.config import get_settings
from app.rag.text import normalize

settings = get_settings()
_CACHE_DIR = Path("/app/data/cache")
_LOCK = threading.Lock()
_INDEX: dict[str, _Bm25] = {}


def tokens(s: str, tokenizer: str) -> list[str]:
    s = normalize(s).lower()
    if not s:
        return []
    if tokenizer == "underthesea":
        from underthesea import word_tokenize

        return word_tokenize(s, format="text").split()
    return s.split()


class _Bm25:
    def __init__(self, ids: list[str], docs: list[list[str]], k1: float, b: float) -> None:
        self.ids, self.k1, self.b = ids, k1, b
        self.len = [len(d) for d in docs]
        self.avg = sum(self.len) / max(len(docs), 1)
        self.post: dict[str, list[tuple[int, int]]] = defaultdict(list)  # từ -> [(doc, tf)]
        for i, d in enumerate(docs):
            for w, tf in Counter(d).items():
                self.post[w].append((i, tf))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for w, p in self.post.items()}

    def top(self, q: list[str], k: int, allowed: set[str] | None) -> list[tuple[str, float]]:
        score: dict[int, float] = defaultdict(float)
        for w in set(q):
            for i, tf in self.post.get(w, ()):
                norm = tf + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg)
                score[i] += self.idf[w] * tf * (self.k1 + 1) / norm
        ranked = sorted(score.items(), key=lambda x: -x[1])
        out = []
        for i, s in ranked:
            if allowed is None or self.ids[i] in allowed:
                out.append((self.ids[i], s))
                if len(out) == k:
                    break
        return out


_TOKENS: dict[str, list[list[str]]] = {}


def _doc_tokens(db, tokenizer: str) -> tuple[list[str], list[list[str]]]:
    """Token của từng node, cache trong bộ nhớ và trên đĩa theo số node. Tách từ là phần
    tốn thời gian nhất (underthesea), nên độc lập với k1/b — đổi k1/b không tách lại."""
    rows = db.execute(text(
        "SELECT node_id, coalesce(heading,'') || ' ' || text FROM legal_node ORDER BY node_id")).all()
    key = f"tok_{tokenizer}_{len(rows)}"
    if key in _TOKENS:
        return [r[0] for r in rows], _TOKENS[key]
    path = _CACHE_DIR / f"{key}.pkl"
    if path.exists():
        with path.open("rb") as f:
            docs = pickle.load(f)
    else:
        logger.info("Tách từ BM25 ({}) cho {} node...", tokenizer, len(rows))
        docs = [tokens(r[1], tokenizer) for r in rows]
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(docs, f)
    _TOKENS.clear()
    _TOKENS[key] = docs
    return [r[0] for r in rows], docs


def _build(db, tokenizer: str) -> _Bm25:
    ids, docs = _doc_tokens(db, tokenizer)
    return _Bm25(ids, docs, settings.bm25_k1, settings.bm25_b)


def search_bm25(db, query: str, k: int, allowed: set[str] | None,
                tokenizer: str | None = None) -> list[tuple[str, float]]:
    tok = tokenizer or settings.bm25_tokenizer
    n = db.execute(text("SELECT count(*) FROM legal_node")).scalar() or 0
    cache_key = f"{tok}:{n}:{settings.bm25_k1}:{settings.bm25_b}"
    with _LOCK:
        if cache_key not in _INDEX:
            _INDEX.clear()
            _INDEX[cache_key] = _build(db, tok)
        idx = _INDEX[cache_key]
    return idx.top(tokens(query, tok), k, allowed)
