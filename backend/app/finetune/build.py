"""Dựng bộ dữ liệu fine-tune từ nguồn CÔNG KHAI (KG1).

Chỉ đọc văn bản luật đã nạp (không phải tệp tải lên), danh mục án lệ và "bài toán" đã
được luật sư duyệt. Câu hỏi sinh ra trùng/gần trùng câu hỏi vàng bị loại để bộ đo còn
giá trị. Ngày tháng và mốc hiệu lực do code quyết, mô hình chỉ chép lại.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import text

from app.finetune import filters, generate

SYSTEM_PROMPT = (
    "Bạn là trợ lý pháp luật lao động Việt Nam. Trả lời ngắn gọn, nêu rõ căn cứ Điều–Khoản "
    "và mốc hiệu lực của văn bản; không bịa điều luật."
)

GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden_v2.jsonl"
LEAK_COSINE = 0.85
VAL_SHARE = 0.05
SCOPES = ("pilot", "laws", "precedents", "all")
PILOT_LAW, PILOT_PRECEDENTS = 20, 5

DOC_LABELS = {"blld2012": "BLLĐ 2012", "blld2019": "BLLĐ 2019", "nd145_2020": "NĐ 145/2020"}


def doc_label(doc_id: str, number: str | None) -> str:
    """Tên ngắn để mô hình chép vào trích dẫn; văn bản mới rơi về số hiệu."""
    return DOC_LABELS.get(doc_id) or (number or doc_id)


def validity_text(valid_from: date | None, valid_to: date | None) -> str:
    """Phần trong ngoặc của mốc hiệu lực, để câu trích dẫn không lặp tên văn bản."""
    if valid_to is not None:
        return f"hết hiệu lực từ {valid_to:%d/%m/%Y}"
    if valid_from is not None:
        return f"hiệu lực từ {valid_from:%d/%m/%Y}"
    return "chưa rõ hiệu lực"


def time_tag(label: str, valid_from: date | None, valid_to: date | None) -> str:
    return f"{label} ({validity_text(valid_from, valid_to)})"


def law_records(db) -> list[dict[str, Any]]:
    """Một bản ghi cho mỗi điều/khoản của văn bản luật thật (bỏ tệp tải lên)."""
    rows = db.execute(
        text(
            "SELECT n.node_id, n.doc_id, n.level, n.article_no, n.clause_no, n.text, "
            "       d.number, d.effective_date, d.expired_date "
            "FROM legal_node n JOIN legal_document d ON d.doc_id = n.doc_id "
            "WHERE coalesce(d.doc_type, '') <> 'upload' AND n.level IN ('article', 'clause') "
            "  AND n.article_no IS NOT NULL "
            "ORDER BY n.doc_id, n.seq"
        )
    ).mappings()
    versions = {
        r["provision_key"]: (r["valid_from"], r["valid_to"])
        for r in db.execute(
            text("SELECT provision_key, valid_from, valid_to FROM provision_version")
        ).mappings()
    }
    out: list[dict[str, Any]] = []
    for r in rows:
        valid_from, valid_to = versions.get(r["node_id"], (None, None))
        valid_from = valid_from or r["effective_date"]
        valid_to = valid_to or r["expired_date"]
        label = doc_label(r["doc_id"], r["number"])
        validity = validity_text(valid_from, valid_to)
        out.append(
            {
                "kind": "law",
                "doc_id": r["doc_id"],
                "doc_label": label,
                "node_id": r["node_id"],
                "level": r["level"],
                "article_no": r["article_no"],
                "clause_no": r["clause_no"],
                "text": r["text"] or "",
                "valid_from": valid_from,
                "valid_to": valid_to,
                "validity": validity,
                "time_tag": f"{label} ({validity})",
            }
        )
    return out


def precedent_records(db) -> list[dict[str, Any]]:
    """90 án lệ trong `precedent_catalog`, kèm toàn văn khi có tệp đã được duyệt."""
    rows = db.execute(
        text(
            "SELECT c.doc_key, c.number, c.title, c.status, u.doc_id AS text_doc_id "
            "FROM precedent_catalog c "
            "LEFT JOIN uploaded_file u ON u.upload_id = c.upload_id AND u.status = 'approved' "
            "ORDER BY c.number DESC"
        )
    ).mappings()
    rows = list(rows)
    doc_ids = [r["text_doc_id"] for r in rows if r["text_doc_id"]]
    texts: dict[str, str] = {}
    if doc_ids:
        for r in db.execute(
            text(
                "SELECT doc_id, text FROM legal_node WHERE doc_id = ANY(:ids) "
                "ORDER BY doc_id, seq"
            ),
            {"ids": doc_ids},
        ).mappings():
            texts[r["doc_id"]] = (texts.get(r["doc_id"], "") + "\n" + (r["text"] or "")).strip()
    out: list[dict[str, Any]] = []
    for r in rows:
        body = texts.get(r["text_doc_id"] or "", "")
        out.append(
            {
                "kind": "precedent",
                "doc_key": r["doc_key"],
                "number": r["number"],
                "precedent_no": f"Án lệ số {r['number']}",
                "title": r["title"] or "",
                "status": r["status"],
                "text": body or (r["title"] or ""),
                "has_full_text": bool(body),
            }
        )
    return out


def approved_problem_records(db) -> list[dict[str, Any]]:
    """Chỉ "bài toán" luật sư đã duyệt (`da_duyet`) — đã che dữ liệu cá nhân."""
    return [
        dict(r)
        for r in db.execute(
            text(
                "SELECT id, title, facts, legal_question, suggested_approach, "
                "       lawyer_analysis, cited_articles "
                "FROM case_problem WHERE status = 'da_duyet' "
                "ORDER BY approved_at DESC NULLS LAST"
            )
        ).mappings()
    ]


def golden_questions(path: Path | None = None) -> list[str]:
    p = path or GOLDEN
    if not p.exists():
        logger.warning("Không thấy bộ câu hỏi vàng {}; bỏ qua bước chống rò rỉ", p)
        return []
    return [
        r["question"]
        for r in map(json.loads, p.read_text(encoding="utf-8").splitlines())
        if r.get("question")
    ]


def drop_golden(
    pairs: list[dict],
    questions: list[str],
    embed_fn: Callable[[list[str]], list[list[float]]] = filters.embed,
) -> tuple[list[dict], int]:
    """Bỏ câu hỏi sinh ra gần trùng (cosine ≥ 0.85) câu hỏi vàng — chống rò rỉ bộ đo."""
    if not pairs or not questions:
        return pairs, 0
    gold = embed_fn(questions)
    vectors = embed_fn([p["question"] for p in pairs])
    kept = [
        pair
        for pair, vec in zip(pairs, vectors, strict=True)
        if all(filters.cosine(vec, g) < LEAK_COSINE for g in gold)
    ]
    return kept, len(pairs) - len(kept)


def chat_row(question: str, answer: str) -> dict:
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }


def _git_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=5
        )
        return res.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def write_dataset(
    out: str | Path,
    pairs: list[dict],
    *,
    rejects: dict[str, int],
    calls: int,
    sources: dict[str, int],
    leaked: int = 0,
    extra: dict[str, Any] | None = None,
    seed: int = 42,
) -> dict[str, Any]:
    """Ghi `train.jsonl`, `val.jsonl` (95/5) và `manifest.json`; trả manifest."""
    path = Path(out)
    path.mkdir(parents=True, exist_ok=True)
    rows = [chat_row(p["question"], p["answer"]) for p in pairs]
    random.Random(seed).shuffle(rows)
    n_val = max(1, round(len(rows) * VAL_SHARE)) if len(rows) > 1 else 0
    val, train = rows[:n_val], rows[n_val:]
    for name, part in (("train.jsonl", train), ("val.jsonl", val)):
        (path / name).write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part), encoding="utf-8"
        )
    counts = {
        "train": len(train),
        "val": len(val),
        "kept": len(rows),
        "generated": len(rows) + sum(rejects.values()) + leaked,
    }
    manifest = {
        "created": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_commit": _git_commit(),
        "sources": sources,
        "counts": counts,
        "rejects": dict(rejects),
        "golden_leak": leaked,
        "dahl_calls": calls,
        **(extra or {}),
    }
    (path / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def select_records(scope: str, records: list[dict], seed: int = 42) -> list[dict]:
    rnd = random.Random(seed)
    law_all = [r for r in records if r["kind"] == "law"]
    current = [r for r in law_all if "hết hiệu lực" not in (r.get("time_tag") or "")]
    repealed = [r for r in law_all if "hết hiệu lực" in (r.get("time_tag") or "")]
    # Luật đã hết hiệu lực chỉ chiếm tối đa 20 % đầu vào (dùng cho câu hỏi có mốc thời gian quá khứ);
    # lô thử đầu: 28/59 cặp trích BLLĐ 2012 cho câu hỏi hiện nay vì kho có rất nhiều điều của luật cũ.
    keep_repealed = min(len(repealed), max(1, len(current) // 4))
    law = current + rnd.sample(repealed, keep_repealed)
    prec = [r for r in records if r["kind"] == "precedent"]
    if scope == "pilot":
        return rnd.sample(law, min(PILOT_LAW, len(law))) + rnd.sample(
            prec, min(PILOT_PRECEDENTS, len(prec))
        )
    if scope == "laws":
        return law
    if scope == "precedents":
        return prec
    return law + prec


def estimate_tokens(records: list[dict], pairs: int) -> int:
    """Ước lượng thô: ~3,5 ký tự/token, vào ~4 000 ký tự văn bản, ra ~700 token/cặp."""
    chars = sum(min(len(r["text"]), generate.MAX_COPY_CHARS) + 400 for r in records)
    out = len(records) * (pairs * 700 + 400)
    return round((chars + out) / 3.5)


def _problem_pairs(problems: list[dict]) -> list[dict]:
    out = []
    for p in problems:
        question = (p.get("legal_question") or p.get("title") or "").strip()
        answer = (p.get("lawyer_analysis") or p.get("suggested_approach") or "").strip()
        if question and answer:
            out.append({"question": question, "answer": answer})
    return out


def _source_id(rec: dict) -> str:
    return rec.get("node_id") or rec.get("doc_key", "")


def _cooling(exc: Exception) -> bool:
    """Lỗi vì hết hạn mức tạm thời (mọi key nghỉ, 429): nên đợi chứ không tính là nguồn hỏng."""
    t = str(exc).lower()
    return "đang nghỉ" in t or "429" in t or "rate limit" in t or "timeout" in t


def _progress(out: Path, i: int, total: int, done: int, failed: int, made: int, started: float,
              *, stopped: bool = False) -> None:
    """progress.json để theo dõi lượt chạy dài (đọc được khi đang chạy)."""
    elapsed = time.monotonic() - started
    eta = (total - i) * (elapsed / i) if i else None
    data = {"processed_this_run": i, "todo_this_run": total, "sources_done_total": done,
            "failed_this_run": failed, "fail_rate": round(failed / made, 3) if made else 0,
            "elapsed_s": round(elapsed), "eta_s": round(eta) if eta is not None else None,
            "stopped_for_failures": stopped, "updated": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out / "progress.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    logger.info("Fine-tune data: {}/{} bản ghi lượt này, lỗi {}", i, total, failed)


def build_dataset(
    db,
    *,
    scope: str = "pilot",
    pairs: int = 3,
    out: str = "data/finetune/pilot",
    dry_run: bool = False,
    max_calls: int = 60,
    seed: int = 42,
    router=None,
    records: list[dict] | None = None,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    golden: list[str] | None = None,
) -> dict[str, Any]:
    """Chạy một lần dựng dữ liệu (hoặc chỉ tính kế hoạch khi `dry_run`).

    `records` cho phép truyền sẵn bản ghi (test, dry-run không DB); `golden=[]` tắt
    bước chống rò rỉ.
    """
    if records is None:
        law = law_records(db)
        prec = precedent_records(db)
        problems = approved_problem_records(db)
        records = law + prec
        sources = {
            "law_records": len(law),
            "precedents": len(prec),
            "case_problems": len(problems),
        }
    else:
        problems = []
        sources = {"records": len(records)}

    chosen = select_records(scope, records, seed)
    # Án lệ chưa có toàn văn thì không sinh: mô hình không được bịa nội dung án lệ.
    generatable = [r for r in chosen if r["kind"] == "law" or r.get("has_full_text")]
    calls = min(len(generatable), max_calls)
    plan = {
        "scope": scope,
        "pairs": pairs,
        "records": len(chosen),
        "calls": calls,
        "est_tokens": estimate_tokens(generatable[:calls], pairs),
        "skipped_no_text": len(chosen) - len(generatable),
        "capped": len(generatable) - calls,
    }
    if dry_run:
        return plan

    if router is None:
        from app.llm.router import get_router

        router = get_router()
    embed_fn = embed_fn or filters.embed
    index = filters.PairIndex([r for r in records if r["kind"] == "law"], embed_fn=embed_fn)
    generated: list[dict] = []
    rejects: Counter[str] = Counter()

    # Chạy dài (hàng nghìn lời gọi): mỗi bản ghi xong thì ghi nối vào raw.jsonl; chạy lại thì bỏ
    # qua bản ghi đã làm. Án lệ duyệt thêm sau có doc_key mới nên lượt sau tự lấy.
    raw_path = Path(out) / "raw.jsonl"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    done: dict[str, list[dict]] = {}
    if raw_path.exists():
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("items"):  # nguồn lỗi (rỗng) được thử lại ở lượt sau
                done[row["source"]] = row["items"]
    todo = [r for r in generatable[:calls] if _source_id(r) not in done]
    failed = made = streak = 0
    started = time.monotonic()
    pause = {"until": 0.0}  # Dahl hết chỗ: mọi luồng cùng nghỉ, không chỉ luồng chính

    def gen_one(rec: dict) -> tuple[list, str]:
        while time.monotonic() < pause["until"]:
            time.sleep(min(30.0, pause["until"] - time.monotonic()))
        items: list = []
        for attempt in range(4):
            try:
                items = (
                    generate.law_pairs(router, rec, pairs)
                    if rec["kind"] == "law"
                    else generate.precedent_card(router, rec)
                )
                break
            except Exception as exc:  # noqa: BLE001 — một bản ghi hỏng không dừng cả lượt
                logger.warning("Sinh dữ liệu lỗi ở {}: {}", _source_id(rec), exc)
                if not _cooling(exc) or attempt == 3:
                    break
                time.sleep(60 * 2 ** attempt)  # mọi key đang nghỉ / 429: đợi rồi thử lại
        return items, getattr(router, "last_provider", "") if items else ""

    from concurrent.futures import ThreadPoolExecutor

    workers = max(1, int(os.environ.get("FT_WORKERS", "1")))  # nhiều key Dahl: gửi song song
    with raw_path.open("a", encoding="utf-8") as raw, ThreadPoolExecutor(workers) as pool:
        results = pool.map(lambda r: (r, *gen_one(r)), todo)
        for i, (rec, items, provider) in enumerate(results, 1):
            made += 1
            if items:
                streak = 0
            else:
                streak += 1
                if streak >= 3:  # nhiều nguồn rỗng liền nhau = Dahl hết chỗ, không phải nguồn hỏng
                    wait = min(900, 60 * 2 ** (streak - 3))
                    logger.info("{} nguồn rỗng liền nhau: đợi {} s cho key Dahl hồi", streak, wait)
                    pause["until"] = max(pause["until"], time.monotonic() + wait)
                else:
                    failed += 1
            row = {"source": _source_id(rec), "items": items, "provider": provider}
            raw.write(json.dumps(row, ensure_ascii=False) + "\n")
            raw.flush()
            done[row["source"]] = items
            if i % 20 == 0 or i == len(todo):
                _progress(Path(out), i, len(todo), len(done), failed, made, started)
            if made >= 100 and failed / made > 0.5:  # nguồn rỗng được làm lại ở lượt sau
                _progress(Path(out), i, len(todo), len(done), failed, made, started, stopped=True)
                raise RuntimeError(f"Dừng: {failed}/{made} lời gọi không ra cặp nào (> 50 %)")

    by_id = {_source_id(r): r for r in generatable}
    for source, items in done.items():
        rec = by_id.get(source, {})
        for item in items:
            why = filters.check_pair(item, index, rec.get("text"))
            if why:
                rejects[why] += 1
                continue
            generated.append({**item, "source": source})

    for item in _problem_pairs(problems):
        why = filters.check_pair(item, index)
        if why:
            rejects[why] += 1
            continue
        generated.append({**item, "source": "case_problem"})

    questions = golden_questions() if golden is None else golden
    kept, leaked = drop_golden(generated, questions, embed_fn=embed_fn)
    manifest = write_dataset(
        out,
        kept,
        rejects=dict(rejects),
        calls=calls,
        sources=sources,
        leaked=leaked,
        extra={"scope": scope, "pairs_requested": pairs, "records_used": calls},
        seed=seed,
    )
    logger.info("Dữ liệu fine-tune: {} cặp, {} lời gọi Dahl", manifest["counts"]["kept"], calls)
    return manifest
