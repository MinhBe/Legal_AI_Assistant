"""Bản án công bố -> che PII -> tình huống (docs/design/case-sources.md).

    GEMINI_FOR_C=true NO_LOCAL_FOR_C=true python -m scripts.judgment_scenarios

Bản án đã ẩn danh một phần ("Tô Đình L"); vẫn che lại bằng luật trong máy (không gọi mô hình) rồi
mới gửi tuyến đám mây mức C. Rút đơn vị bằng bước 2 của prompt v2.1 (văn bản đã có dấu, không cần
bước sửa lời nói). Đầu ra: data/scenarios/cases_v1.jsonl, cùng lược đồ recordings_v1.jsonl;
chạy lại thì bỏ bản án đã làm.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.audio.spoken_pii import mask_spoken
from app.db.base import SessionLocal
from app.intake.analyze import corpus_docs
from app.llm.context import cloud_first_scope, data_class_scope
from app.llm.router import get_router, parse_json
from app.problems import spoken_v2
from scripts.recordings_scenarios import corpus_status

SRC = Path("data/raw/cases/congbobanan")
OUT = Path("data/scenarios/cases_v1.jsonl")
MAX_CHARS = 24_000


def body(text: str) -> str:
    """Giữ phần nội dung vụ án, nhận định, quyết định; bỏ phần đầu thủ tục nếu quá dài."""
    t = " ".join(text.split())
    i = t.upper().find("NỘI DUNG VỤ ÁN")
    if i > 0 and len(t) > MAX_CHARS:
        t = t[i:]
    return t[:MAX_CHARS]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    done = {json.loads(x)["case_id"] for x in OUT.read_text(encoding="utf-8").splitlines() if x} \
        if OUT.exists() else set()
    db = SessionLocal()
    try:
        docs = corpus_docs(db)
    finally:
        db.close()
    router = get_router()
    n_ok = n_err = 0
    with OUT.open("a", encoding="utf-8") as out:
        for p in sorted(SRC.glob("*.json")):
            case = json.loads(p.read_text(encoding="utf-8"))
            if case["id"] in done:
                continue
            masked = mask_spoken(body(case["text"]), mapping={})
            try:
                with data_class_scope("C"), cloud_first_scope(True):
                    raw = router.chat([{"role": "system", "content": spoken_v2.STAGE2_SYSTEM},
                                       {"role": "user", "content": spoken_v2.stage2_user(masked, docs)}],
                                      task="route", temperature=0.2).text
                units = parse_json(raw).get("units") or []
            except Exception as exc:  # noqa: BLE001 — lượt sau làm lại
                print(case["id"], "lỗi:", str(exc)[:120], flush=True)
                n_err += 1
                continue
            for i, u in enumerate(units):
                if not isinstance(u, dict):
                    continue
                cites = [{"doc": c.get("doc", ""), "article": c.get("article", ""),
                          "status": corpus_status(c.get("doc", "")),
                          "source": "judgment" if c.get("source") == "audio" else c.get("source", "model")}
                         for c in u.get("citations") or [] if isinstance(c, dict)]
                out.write(json.dumps({
                    "id": f"case-{case['id']}-{i}", "case_id": case["id"], "source": "judgment",
                    "url": case["url"], "case_type": case["meta"].get("loai", ""),
                    "court_level": case["meta"].get("Cấp xét xử", ""),
                    "domain": u.get("domain", ""), "facts": u.get("facts") or [],
                    "legal_question": u.get("legal_question", ""),
                    "court_says": u.get("lawyer_says") or [], "articles": cites,
                    "suggestions": u.get("suggestions") or [],
                    "uncertain": u.get("uncertain") or [],
                    "model": getattr(router, "last_provider", ""),
                    "review": "pending_lawyer_review"}, ensure_ascii=False) + "\n")
            out.flush()
            n_ok += 1
            print(case["id"], len(units), "đơn vị", flush=True)
    print("xong:", n_ok, "bản án,", n_err, "lỗi")


if __name__ == "__main__":
    main()
