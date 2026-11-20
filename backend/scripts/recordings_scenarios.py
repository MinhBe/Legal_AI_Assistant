"""5 ghi âm (bản ĐÃ CHE) -> đơn vị v2.1 (GLM) -> "giả định / tình huống" cho bộ luật.

    python -m scripts.recordings_scenarios --run      # GLM-5.3-Flash, cửa sổ 15 phút, chạy lại được
    python -m scripts.recordings_scenarios --export   # data/scenarios/recordings_v1.jsonl + .md

Mỗi tình huống: tình tiết -> câu hỏi pháp lý -> điều luật (trạng thái kiểm) -> gợi ý.
Trạng thái điều luật:
- verified_in_corpus: văn bản có trong kho, đã duyệt;
- in_corpus_pending_approval: có trong kho nhưng đang chờ duyệt ở /upload;
- outside_corpus_unverified: không có trong kho (mô hình hoặc luật sư nhắc), cần kiểm.
Chỉ bản đã che được gửi lên đám mây (mức C).
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from scripts.spoken_v2_eval import MODELS, caller, load_window

# GLM thắng bake-off nên đi đầu; GLM hết chỗ thì sang model Dahl khác (vẫn bản đã che, mức C)
DAHL_ORDER = ["zai-org/GLM-5.3-Flash", "MiniMaxAI/MiniMax-M2.7", "deepseek-ai/DeepSeek-V4-Flash-0731"]


def dahl_caller(stats: dict):
    import time

    from app.llm.context import cloud_first_scope, data_class_scope
    from app.llm.router import get_router

    router = get_router()

    def call(messages):
        for rnd in range(6):
            for model in DAHL_ORDER:
                try:
                    with data_class_scope("C"), cloud_first_scope(True):
                        res = router._call_cloud(model, messages, 0.2, 6000, task="route")  # noqa: SLF001
                    stats["calls"] += 1
                    stats.setdefault("models", []).append(model)
                    return res.text
                except Exception as exc:  # noqa: BLE001 — model hết chỗ: thử model kế
                    last = exc
            time.sleep(60 * (rnd + 1))
        raise last

    return call

from app.problems import spoken_v2

REC = Path("data/raw/record/out")
RUN = REC / "v2" / "scenarios"
OUT = Path("data/scenarios")
WINDOW = 900

# Kho hiện tại (19/11/2026). Đã duyệt: lao động. Còn lại: chờ duyệt ở /upload.
APPROVED = [
    "Bộ luật Lao động 2019 (45/2019/QH14)",
    "Bộ luật Lao động 2012 (10/2012/QH13, hết hiệu lực)",
    "Nghị định 145/2020/NĐ-CP",
]
PENDING = [
    "Bộ luật Dân sự 2015 (91/2015/QH13)",
    "Bộ luật Hình sự (100/2015/QH13, VBHN 135/VBHN-VPQH)",
    "Luật Đất đai 2024 (31/2024/QH15, VBHN 44/VBHN-VPQH)",
    "Nghị định 101/2024/NĐ-CP (đăng ký, cấp Giấy chứng nhận)",
    "Nghị định 102/2024/NĐ-CP (chi tiết Luật Đất đai)",
    "Nghị định 282/2025/NĐ-CP (xử phạt VPHC an ninh, trật tự)",
    "Luật Hôn nhân và gia đình (52/2014/QH13, VBHN 121/VBHN-VPQH)",
    "Luật Thuế thu nhập cá nhân 2025 (109/2025/QH15)",
    "Nghị định 399/2026/NĐ-CP (lương tối thiểu)",
]
CORPUS = APPROVED + PENDING

# khoá nhận diện văn bản trong trích dẫn -> có trong kho đã duyệt hay chờ duyệt
_KEYS = {
    r"45/2019|lao động 2019|bộ luật lao động(?! 2012)": "approved",
    r"10/2012|lao động 2012": "approved",
    r"145/2020": "approved",
    r"91/2015|dân sự": "pending",
    r"100/2015|hình sự|135/vbhn": "pending",
    r"31/2024|đất đai|44/vbhn": "pending",
    r"101/2024": "pending",
    r"102/2024": "pending",
    r"282/2025": "pending",
    r"52/2014|hôn nhân": "pending",
    r"109/2025|thu nhập cá nhân": "pending",
    r"399/2026": "pending",
}


def corpus_status(doc: str) -> str:
    d = doc.lower()
    # nghị định khác số với các NĐ trong kho thì không tính là "đất đai"/"hình sự"…
    nd = re.search(r"(\d+/\d{4})/nđ-cp", d)
    if nd and not any(nd.group(1) in k for k in _KEYS):
        return "outside_corpus_unverified"
    for pat, kind in _KEYS.items():
        if re.search(pat, d):
            return "verified_in_corpus" if kind == "approved" else "in_corpus_pending_approval"
    return "outside_corpus_unverified"


def stems() -> list[str]:
    return sorted(p.name[: -len(".masked.json")] for p in REC.glob("*_AUDIO.masked.json"))


def run(model: str = "glm") -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    kind, name = MODELS[model]
    for stem in stems():
        segs = json.loads((REC / f"{stem}.masked.json").read_text(encoding="utf-8"))["segments"]
        end = segs[-1]["end"]
        for a in range(0, int(end) + 1, WINDOW):
            path = RUN / f"{stem}_{a}_{a + WINDOW}.{model}.json"
            if path.exists():
                continue
            sources = load_window(stem, a, a + WINDOW)
            if not sources.get("A", "").strip():
                continue
            stats = {"calls": 0, "seconds": 0.0, "ids": []}
            call = dahl_caller(stats) if model == "glm" else caller(kind, name, stats)
            result = spoken_v2.run(call, sources, CORPUS)
            if not result["units"] and result["errors"]:
                print(path.name, "LỖI, chạy lại sau:", result["errors"], flush=True)
                continue  # không ghi tệp -> lượt sau thử lại
            result["audit"] = spoken_v2.audit(result, "\n".join(sources.values()), CORPUS)
            result["enforced"] = spoken_v2.enforce(result, CORPUS)
            result["stats"] = {k: v for k, v in stats.items() if k != "ids"}
            path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
            print(path.name, len(result["units"]), "đơn vị", result["audit"], flush=True)


def to_scenario(stem: str, window: str, i: int, u: dict, models: str = "GLM-5.3-Flash") -> dict:
    cites = []
    for c in u.get("citations") or []:
        status = corpus_status(c.get("doc", ""))
        cites.append({"doc": c.get("doc", ""), "article": c.get("article", ""),
                      "status": status, "source": c.get("source", "model"),
                      "needs_check": status != "verified_in_corpus"})
    return {
        "id": f"rec-{stem[:8]}-{window}-{i}",
        "recording": stem,
        "time": f"{u.get('start', '')}–{u.get('end', '')}",
        "domain": u.get("domain", ""),
        "in_scope_labour": u.get("in_scope_labour", "no"),
        "facts": u.get("facts") or [],
        "legal_question": u.get("legal_question", ""),
        "lawyer_says": u.get("lawyer_says") or [],
        "articles": cites,
        "suggestions": u.get("suggestions") or [],
        "practical_tactics": u.get("practical_tactics") or [],
        "uncertain": u.get("uncertain") or [],
        "source": "recording-masked",
        "model": f"{models}, prompt v2.1",
        "review": "pending_lawyer_review",
    }


def export() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in sorted(RUN.glob("*.glm.json")):
        stem, window = p.name.split(".")[0].rsplit("_", 2)[0], "_".join(p.name.split(".")[0].rsplit("_", 2)[1:])
        res = json.loads(p.read_text(encoding="utf-8"))
        models = ", ".join(sorted({m.split("/")[-1] for m in res.get("stats", {}).get("models", [])}))             or "GLM-5.3-Flash"
        for i, u in enumerate(res["units"]):
            if u.get("legal_question") or u.get("facts"):
                rows.append(to_scenario(stem, window, i, u, models))
    with (OUT / "recordings_v1.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    lines = ["# Tình huống từ 5 ghi âm (v1)", "",
             f"{len(rows)} tình huống, sinh bằng GLM-5.3-Flash theo prompt v2.1 trên bản đã che PII.",
             "Tất cả đang **chờ luật sư duyệt**. Trạng thái điều luật: ✔ trong kho đã duyệt, "
             "⏳ trong kho chờ duyệt, ✖ ngoài kho (cần kiểm).", ""]
    mark = {"verified_in_corpus": "✔", "in_corpus_pending_approval": "⏳",
            "outside_corpus_unverified": "✖"}
    by_domain: dict[str, list] = {}
    for r in rows:
        by_domain.setdefault(r["domain"] or "khác", []).append(r)
    for dom, rs in sorted(by_domain.items(), key=lambda kv: -len(kv[1])):
        lines += [f"## {dom} ({len(rs)})", ""]
        for r in rs:
            lines.append(f"### {r['legal_question'] or '(chưa rõ câu hỏi)'}")
            lines.append(f"*{r['id']} · {r['time']}*")
            if r["facts"]:
                lines.append("- **Tình tiết:** " + " ".join(r["facts"]))
            for c in r["articles"]:
                lines.append(f"- {mark[c['status']]} {c['doc']} {c['article']}".rstrip())
            for s in r["suggestions"][:3]:
                lines.append(f"- Gợi ý: {s['text'] if isinstance(s, dict) else s}")
            lines.append("")
    (OUT / "recordings_v1.md").write_text("\n".join(lines), encoding="utf-8")
    print(len(rows), "tình huống ->", OUT)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--export", action="store_true")
    ap.add_argument("--model", default="glm")
    a = ap.parse_args()
    if a.run:
        run(a.model)
    if a.export:
        export()


if __name__ == "__main__":
    main()
