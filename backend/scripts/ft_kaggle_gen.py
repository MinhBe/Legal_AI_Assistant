"""Sinh dữ liệu train bằng model mở trên Kaggle GPU (thử nghiệm, Minh 20/11/2026: bớt phụ thuộc Dahl).

    python -m scripts.ft_kaggle_gen export --n 30            # prompt của nguồn còn thiếu -> jsonl
    python -m scripts.ft_kaggle_gen import --compare         # đo tỉ lệ qua bộ lọc, so với Dahl
    python -m scripts.ft_kaggle_gen import --write-raw       # ghi vào data/finetune/full/raw.jsonl

Prompt dựng bằng đúng generate.law_pairs / precedent_card (router ghi lại thay vì gọi); kết quả
Kaggle được "phát lại" qua cùng hàm đó nên bước parse và kiểm JSON giống hệt. Chỉ văn bản luật và
án lệ công khai; không key, không ghi âm, không bộ câu hỏi vàng.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from app.db.base import SessionLocal
from app.finetune import build, filters, generate

DIR = Path("data/finetune/kaggle_gen")
RAW = Path("data/finetune/full/raw.jsonl")


class _Capture(Exception):
    pass


class CaptureRouter:
    def __init__(self) -> None:
        self.messages: list[dict] | None = None

    def chat(self, messages, **kw):
        if self.messages is None:  # chỉ giữ lời gọi đầu; lời hỏi lại (sửa JSON) bỏ qua
            self.messages = messages
        raise _Capture


class ReplayRouter:
    """Trả lại văn bản Kaggle đã sinh; lần hỏi lại (sửa JSON) nhận cùng văn bản."""

    def __init__(self, text: str) -> None:
        self.text = text

    def chat(self, messages, **kw):
        return type("R", (), {"text": self.text})()


def _records() -> tuple[list[dict], list[dict]]:
    db = SessionLocal()
    try:
        law = build.law_records(db)
        records = law + build.precedent_records(db)
    finally:
        db.close()
    chosen = build.select_records("all", records, 42)
    gen = [r for r in chosen if r["kind"] == "law" or r.get("has_full_text")]
    return gen, law


def _done() -> set[str]:
    out = set()
    if RAW.exists():
        for line in RAW.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("items"):
                out.add(row["source"])
    return out


def _run(router, rec: dict) -> list[dict]:
    return (generate.law_pairs(router, rec, 3) if rec["kind"] == "law"
            else generate.precedent_card(router, rec))


def export(n: int) -> None:
    gen, _ = _records()
    done = _done()
    todo = [r for r in gen if build._source_id(r) not in done][:n]  # noqa: SLF001
    DIR.mkdir(parents=True, exist_ok=True)
    with (DIR / "prompts.jsonl").open("w", encoding="utf-8") as f:
        for rec in todo:
            cap = CaptureRouter()
            try:
                _run(cap, rec)
            except _Capture:
                pass
            if cap.messages:
                f.write(json.dumps({"source": build._source_id(rec), "messages": cap.messages},  # noqa: SLF001
                                   ensure_ascii=False) + "\n")
    print(len(todo), "prompt ->", DIR / "prompts.jsonl")


def _index(law: list[dict]) -> filters.PairIndex:
    # so sánh tỉ lệ qua bộ lọc: tắt bước trùng lặp (cần embedding) để không nạp model trong máy
    i = [0]

    def fake(texts):
        out = []
        for _ in texts:
            i[0] += 1
            v = [0.0] * 8
            v[i[0] % 8] = 1.0 + i[0]
            out.append(v)
        return out

    idx = filters.PairIndex(law, embed_fn=fake)
    idx.kept = []
    idx.add = lambda q: None  # không ghi câu đã giữ -> không xét trùng
    return idx


def _rate(rows: list[tuple[dict, list[dict]]], law: list[dict]) -> dict:
    idx = _index(law)
    why: Counter[str] = Counter()
    total = kept = empty = 0
    for rec, items in rows:
        if not items:
            empty += 1
        for it in items:
            total += 1
            r = filters.check_pair(it, idx, rec.get("text"))
            if r is None:
                kept += 1
            else:
                why[r] += 1
    return {"sources": len(rows), "empty_sources": empty, "pairs": total, "kept": kept,
            "pass_rate": round(kept / total, 3) if total else 0.0, "rejects": dict(why)}


def do_import(compare: bool, write_raw: bool) -> None:
    gen, law = _records()
    by_id = {build._source_id(r): r for r in gen}  # noqa: SLF001
    outs = [json.loads(x) for x in (DIR / "out" / "outputs.jsonl").read_text(encoding="utf-8").splitlines() if x]
    model = outs[0].get("model", "kaggle") if outs else "kaggle"
    kag = [(by_id[o["source"]], _run(ReplayRouter(o["text"]), by_id[o["source"]]))
           for o in outs if o["source"] in by_id]
    print("Kaggle", model, _rate(kag, law))
    if compare:
        dahl = []
        for line in RAW.read_text(encoding="utf-8").splitlines()[-400:]:
            row = json.loads(line)
            if row.get("items") and row["source"] in by_id:
                dahl.append((by_id[row["source"]], row["items"]))
        print("Dahl/Gemini (400 dòng cuối)", _rate(dahl[-len(kag) * 3:], law))
    if write_raw:
        with RAW.open("a", encoding="utf-8") as f:
            for rec, items in kag:
                if items:
                    f.write(json.dumps({"source": build._source_id(rec), "items": items,  # noqa: SLF001
                                        "provider": f"kaggle:{model}"}, ensure_ascii=False) + "\n")
        print("đã ghi", sum(1 for _, i in kag if i), "nguồn vào", RAW)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["export", "import"])
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--write-raw", action="store_true")
    a = ap.parse_args()
    if a.cmd == "export":
        export(a.n)
    else:
        do_import(a.compare, a.write_raw)


if __name__ == "__main__":
    main()
