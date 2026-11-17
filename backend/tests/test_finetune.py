"""Contract KG1 — kit fine-tune: dựng dữ liệu, lọc, chống rò rỉ. Không mạng, không LLM, không GPU."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.finetune import build, filters, generate

TAG19 = "BLLĐ 2019 (hiệu lực từ 01/01/2021)"
TAG12 = "BLLĐ 2012 (hết hiệu lực từ 01/01/2021)"

RECORDS = [
    {
        "kind": "law", "doc_id": "blld2019", "doc_label": "BLLĐ 2019", "node_id": "blld2019-d35",
        "level": "article", "article_no": 35, "clause_no": None, "text": "Điều 35. Nội dung",
        "time_tag": TAG19,
    },
    {
        "kind": "law", "doc_id": "blld2019", "doc_label": "BLLĐ 2019", "node_id": "blld2019-d35-k2",
        "level": "clause", "article_no": 35, "clause_no": 2, "text": "Nội dung khoản 2",
        "time_tag": TAG19,
    },
    {
        "kind": "law", "doc_id": "blld2012", "doc_label": "BLLĐ 2012", "node_id": "blld2012-d35",
        "level": "article", "article_no": 35, "clause_no": None, "text": "Điều 35 (bản cũ)",
        "time_tag": TAG12,
    },
]

GOOD_Q = "Công ty chấm dứt hợp đồng lao động trước 45 ngày thì có phải báo trước cho tôi không?"
GOOD_A = (
    "Điều 35 khoản 2 BLLĐ 2019 (hiệu lực từ 01/01/2021) quy định người sử dụng lao động phải "
    "báo trước bằng văn bản cho người lao động khi chấm dứt hợp đồng lao động, trừ các trường "
    "hợp pháp luật quy định không cần báo trước."
)


def _fake_embed(texts: list[str]) -> list[list[float]]:
    """Vector túi từ (băm ổn định) — đủ thử logic gần trùng mà không tải model embedding."""
    out = []
    for t in texts:
        vec = [0.0] * 256
        for word in t.lower().split():
            idx = int.from_bytes(hashlib.md5(word.encode("utf-8")).digest()[:4], "big") % 256
            vec[idx] += 1.0
        out.append(vec)
    return out


def _index() -> filters.PairIndex:
    return filters.PairIndex(RECORDS, embed_fn=_fake_embed)


def _pair(question: str = GOOD_Q, answer: str = GOOD_A) -> dict:
    return {"question": question, "answer": answer}


@pytest.mark.db
def test_law_records_time_tags(db):
    records = build.law_records(db)
    old = [r for r in records if r["doc_id"] == "blld2012"]
    new = [r for r in records if r["doc_id"] == "blld2019"]
    assert old and new, "kho phải có BLLĐ 2012 và BLLĐ 2019"
    assert {r["time_tag"] for r in old} == {TAG12}
    assert {r["time_tag"] for r in new} == {TAG19}
    assert all(r["doc_label"] == build.DOC_LABELS[r["doc_id"]] for r in old + new)
    assert all(not r["doc_id"].startswith("up_") for r in records), "không lấy tệp tải lên"


def test_filter_rejects_invented_article():
    answer = (
        "Điều 999 khoản 1 BLLĐ 2019 (hiệu lực từ 01/01/2021) quy định về việc báo trước khi "
        "chấm dứt hợp đồng lao động, áp dụng cho mọi trường hợp người lao động đơn phương "
        "chấm dứt."
    )
    assert _index().check(GOOD_Q, answer) == "cited_missing"


def test_filter_rejects_wrong_time_tag():
    answer = GOOD_A.replace("hiệu lực từ", "hết hiệu lực từ")
    assert _index().check(GOOD_Q, answer) == "time_tag"


def test_filter_rejects_near_duplicate_and_keeps_good_pair():
    index = _index()
    assert index.check(GOOD_Q, GOOD_A) is None
    index.add(GOOD_Q)
    assert index.check(GOOD_Q, GOOD_A) == "near_duplicate"


def test_prompt_citation_line_passes_filter():
    """Dòng "Trích dẫn đúng dạng" phải khớp bộ lọc: không lặp tên văn bản."""
    record = {
        "doc_label": "BLLĐ 2019", "time_tag": TAG19, "validity": "hiệu lực từ 01/01/2021",
        "article_no": 35, "clause_no": 2, "text": "Nội dung khoản 2",
    }
    line = next(
        ln for ln in generate._law_user(record, 1).splitlines() if ln.startswith("Trích dẫn")
    )
    cite = line.removeprefix("Trích dẫn đúng dạng: ").rstrip(".")
    assert cite == "Điều 35 khoản 2 BLLĐ 2019 (hiệu lực từ 01/01/2021)"
    answer = cite + GOOD_A.split(")", 1)[1]
    assert _index().check(GOOD_Q, answer) is None


def test_golden_leakage_dropped():
    golden = ["Người lao động được nghỉ phép năm bao nhiêu ngày?"]
    pairs = [
        {"question": golden[0], "answer": GOOD_A},
        {"question": "Hợp đồng thử việc tối đa bao nhiêu ngày theo luật hiện hành?", "answer": GOOD_A},
    ]
    kept, leaked = build.drop_golden(pairs, golden, embed_fn=_fake_embed)
    assert leaked == 1
    assert [p["question"] for p in kept] == [pairs[1]["question"]]


class _DeadRouter:
    """Mọi lời gọi router đều là lỗi: `--dry-run` không được gọi mô hình."""

    def __getattr__(self, name: str):
        raise AssertionError(f"--dry-run không được gọi router.{name}")


def test_dry_run_counts_calls_without_router(tmp_path):
    records = [*RECORDS, {
        "kind": "precedent", "doc_key": "K1", "number": "1/2021/AL",
        "precedent_no": "Án lệ số 1/2021/AL", "title": "Tiêu đề", "status": "dang_ap_dung",
        "text": "x" * 400, "has_full_text": True,
    }, {
        "kind": "precedent", "doc_key": "K2", "number": "2/2021/AL",
        "precedent_no": "Án lệ số 2/2021/AL", "title": "Chưa có toàn văn", "status": "chua_ro",
        "text": "Chưa có toàn văn", "has_full_text": False,
    }]
    out = tmp_path / "out"
    plan = build.build_dataset(
        None, scope="all", pairs=2, out=str(out), dry_run=True, router=_DeadRouter(), records=records
    )
    assert plan["calls"] == 4, "3 điều/khoản + 1 án lệ có toàn văn"
    assert plan["skipped_no_text"] == 1
    assert plan["est_tokens"] > 0
    assert not out.exists(), "--dry-run không được ghi tệp"

    capped = build.build_dataset(
        None, scope="laws", pairs=2, out=str(out), dry_run=True, max_calls=2,
        router=_DeadRouter(), records=records,
    )
    assert capped["calls"] == 2 and capped["capped"] == 1


def test_output_is_chat_jsonl_and_manifest_adds_up(tmp_path):
    pairs = [
        {"question": f"Câu hỏi tình huống số {i} về báo trước khi nghỉ việc?", "answer": GOOD_A}
        for i in range(20)
    ]
    rejects = {"time_tag": 1, "near_duplicate": 2}
    manifest = build.write_dataset(
        tmp_path / "run",
        pairs,
        rejects=rejects,
        calls=5,
        sources={"law_records": 3, "precedents": 1},
        leaked=1,
    )
    train = [
        json.loads(line)
        for line in (tmp_path / "run" / "train.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    val = [
        json.loads(line)
        for line in (tmp_path / "run" / "val.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    for row in train + val:
        roles = [m["role"] for m in row["messages"]]
        assert roles == ["system", "user", "assistant"]
        assert all(m["content"].strip() for m in row["messages"])

    counts = manifest["counts"]
    assert counts["train"] == len(train) and counts["val"] == len(val)
    assert counts["kept"] == len(train) + len(val) == len(pairs)
    assert counts["generated"] == counts["kept"] + sum(rejects.values()) + 1
    assert manifest["dahl_calls"] == 5
    assert json.loads((tmp_path / "run" / "manifest.json").read_text(encoding="utf-8")) == manifest


def test_finetune_scripts_compile():
    roots = [Path("/finetune"), Path(__file__).resolve().parents[2].parent / "finetune"]
    files = [
        p for root in roots if root.is_dir() for name in ("train.py", "export_gguf.py")
        if (p := root / name).exists()
    ]
    if not files:
        pytest.skip("finetune/ không có trong container — kiểm bằng py_compile trên máy chủ")
    subprocess.run([sys.executable, "-m", "py_compile", *map(str, files)], check=True)


def test_repealed_law_needs_a_past_event_date_and_vague_answers_are_rejected():
    from app.finetune.filters import _time_and_grounding

    a = "Theo Điều 98 khoản 3 BLLĐ 2012 (hết hiệu lực từ 01/01/2021), tiền lương ngừng việc do hai bên thoả thuận."
    assert _time_and_grounding("Doanh nghiệp tôi ngừng việc vì dịch, có phải trả lương?", a, None) == \
        "repealed_without_past_date"
    assert _time_and_grounding("Tháng 6/2020 công ty tôi ngừng việc vì dịch, có phải trả lương?", a, None) is None
    src = ("Hồ sơ đề nghị gia hạn giấy phép lao động gồm: văn bản đề nghị gia hạn; giấy phép lao động còn thời hạn; "
           "giấy chứng nhận sức khỏe; văn bản chấp thuận nhu cầu sử dụng người lao động nước ngoài; "
           "bản sao hộ chiếu còn giá trị; giấy tờ chứng minh người lao động tiếp tục làm việc.")
    vague = "Theo Điều 26 khoản 2 NĐ 145/2020, hồ sơ gồm các giấy tờ theo quy định, bạn nên liên hệ cơ quan để được hướng dẫn."
    assert _time_and_grounding("Hồ sơ gia hạn giấy phép lao động gồm gì?", vague, src) == "not_grounded"
