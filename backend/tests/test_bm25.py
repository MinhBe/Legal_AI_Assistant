"""BM25 trong bộ nhớ (app/rag/bm25.py): thuần Python, không cần DB."""

from app.rag.bm25 import _Bm25, tokens


def _idx(texts, tokenizer="syllable"):
    return _Bm25([f"d{i}" for i in range(len(texts))], [tokens(t, tokenizer) for t in texts],
                k1=1.5, b=0.75)


def test_document_with_the_matching_word_ranks_first():
    idx = _idx([
        "người lao động được nghỉ hằng năm",
        "thời gian thử việc tối đa",
        "làm thêm giờ ban đêm",
    ])
    top = idx.top(tokens("nghỉ hằng năm", "syllable"), k=3, allowed=None)
    assert top[0][0] == "d0"


def test_allowed_set_excludes_the_matching_document():
    idx = _idx(["nghỉ hằng năm", "thử việc", "làm thêm giờ"])
    top = idx.top(tokens("nghỉ hằng năm", "syllable"), k=3, allowed={"d1", "d2"})
    assert "d0" not in [i for i, _ in top]


def test_tokens_syllable_splits_on_whitespace_lowercased():
    assert tokens("Người  Lao động", "syllable") == ["người", "lao", "động"]


def test_tokens_underthesea_joins_compound_words():
    out = tokens("người lao động được nghỉ hằng năm", "underthesea")
    assert "lao_động" in out  # không tách rời "lao" và "động" như syllable
