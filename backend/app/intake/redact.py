"""Phát hiện đoạn nhạy cảm và áp lựa chọn làm mờ của người dùng (voice intake, 20/11/2026).

Chỉ chạy luật trong máy (`spoken_pii`, không gọi mô hình): người dùng xem từng đoạn rồi tự chọn
- "pseudonym": thay tên giả nhất quán theo người (Nguyễn Văn B / Nguyễn Thị B / Người B,
  Công ty X, [địa chỉ], [số đã ẩn]);
- "generalize": TÌNH_TIẾT thành "[tình tiết nhạy cảm, đã ẩn]", loại khác như pseudonym;
- "keep": giữ nguyên (cần để hiểu vụ việc).
Mặc định mọi đoạn là "pseudonym" hoặc "generalize".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.audio.spoken_pii import mask_spoken

ACTIONS = ("pseudonym", "generalize", "keep")
LETTERS = "BCDEGHKLMNPQRSTUVXY"
ORG_LETTERS = "XYZWVUTS"
GROUP = {"TÊN": "person", "TỔ_CHỨC": "organization", "ĐỊA_CHỈ": "contact", "SĐT": "contact",
         "STK": "contact", "CCCD": "contact", "EMAIL": "contact", "SỐ": "contact",
         "TÌNH_TIẾT": "sensitive_fact"}

_SENSITIVE = re.compile(
    r"(?<!\w)(?:hiv|aids|ung thư|bệnh|tâm thần|trầm cảm|có thai|mang thai|phá thai|sảy thai|"
    r"tiền án|tiền sự|ngồi tù|đi tù|án tù|bị bắt|ma tuý|ma túy|nghiện|ngoại tình|"
    r"quan hệ tình dục|xâm hại|hiếp|bạo lực|đánh đập|bạo hành|nợ xấu|vỡ nợ|tôn giáo|"
    r"đồng tính|chuyển giới|ly hôn|tự tử|nhiễm)(?!\w)",
    re.IGNORECASE,
)
_U = "A-ZĂÂĐÊÔƠƯÀÁẢÃẠẰẮẲẴẶẦẤẨẪẬÈÉẺẼẸỀẾỂỄỆÌÍỈĨỊÒÓỎÕỌỒỐỔỖỘỜỚỞỠỢÙÚỦŨỤỪỨỬỮỰỲÝỶỸỴ"
# tên doanh nghiệp gõ chữ hoa: "Công ty TNHH Hoà Bình", "Ngân hàng ABC"
_ORG = re.compile(
    rf"(?<!\w)(?:[Cc]ông ty|[Cc]ty|[Tt]ập đoàn|[Nn]gân hàng|[Dd]oanh nghiệp|[Hh]ợp tác xã)"
    rf"(?:[ \t]+(?:TNHH|CP|MTV|cổ phần|trách nhiệm hữu hạn|một thành viên|tư nhân))*"
    rf"[ \t]+[{_U}0-9][\w&-]*(?:[ \t]+[{_U}0-9][\w&-]*){{0,5}}"
)
_STOP = (r"bị|là|làm|có|đã|ở|và|nợ|thì|mà|được|không|nên|vì|với|cho|của|đang|sẽ|tại|về|"
         r"từ|nhưng|hay|hoặc|rồi|khi|để|này|đó|nay|năm|tháng")
# lời nói chữ thường: "công ty may việt tiến bị nợ lương" -> dừng ở động từ/hư từ
_ORG_SPOKEN = re.compile(
    rf"(?<!\w)(?:công ty|cty|tập đoàn|ngân hàng|doanh nghiệp|hợp tác xã)"
    rf"(?:\s+(?!(?:{_STOP})(?!\w))[\wÀ-ỹ]+){{1,5}}",
    re.IGNORECASE,
)
_TRAIL = re.compile(rf"(?:\s+(?:{_STOP}))+$", re.IGNORECASE)
_SENTENCE = re.compile(r"[^.?!\n]+[.?!]?")
_MALE = re.compile(r"(?<!\w)(?:anh|ông|chú|bác trai|cậu|văn)(?!\w)", re.IGNORECASE)
_FEMALE = re.compile(r"(?<!\w)(?:chị|bà|cô|thím|mợ|dì|thị)(?!\w)", re.IGNORECASE)


@dataclass
class Span:
    id: str
    type: str
    group: str
    entity: str  # đoạn cùng một người/đơn vị chung entity -> tên giả nhất quán
    text: str
    start: int
    end: int
    suggestion: str
    default: str


def _occurrences(text: str, value: str):
    body = r"\s+".join(re.escape(w) for w in value.split())
    for m in re.finditer(rf"(?<!\w){body}(?!\w)", text, re.IGNORECASE):
        yield m.start(), m.end()


def _gender(text: str, value: str, start: int) -> str:
    if re.search(r"(?<!\w)thị(?!\w)", value, re.IGNORECASE):
        return "f"
    if re.search(r"(?<!\w)văn(?!\w)", value, re.IGNORECASE):
        return "m"
    before = text[max(0, start - 12):start]
    if _FEMALE.search(before):
        return "f"
    if _MALE.search(before):
        return "m"
    return "?"


def detect(text: str) -> list[dict]:
    mapping: dict[str, str] = {}
    mask_spoken(text, mapping=mapping)
    for ph in list(mapping):  # "trần thị hoa làm" -> "trần thị hoa"
        v = _TRAIL.sub("", mapping[ph])
        if v:
            mapping[ph] = v
    for rx in (_ORG, _ORG_SPOKEN):
        for m in rx.finditer(text):
            v = m.group(0)
            if len(v.split()) > 2 and not any(v.lower() in x.lower() or x.lower() in v.lower()
                                              for x in mapping.values()):
                mapping[f"[TỔ_CHỨC_{100 + len(mapping)}]"] = v
    # tên gọi tắt ("An") của một họ tên đầy đủ ("Nguyễn Văn An") là cùng một người
    full = {ph: v for ph, v in mapping.items() if ph.startswith("[TÊN") and len(v.split()) > 1}
    alias: dict[str, str] = {}
    for ph, v in mapping.items():
        if ph.startswith("[TÊN") and len(v.split()) == 1:
            owner = [p for p, fv in full.items() if fv.split()[-1].lower() == v.lower()]
            if len(owner) == 1:
                alias[ph] = owner[0]
    seen_people: dict[str, str] = {}
    spans: list[Span] = []
    taken: list[tuple[int, int]] = []
    people = orgs = 0
    # giá trị dài trước để "Nguyễn Văn An" không bị tách thành "An"
    for ph, value in sorted(mapping.items(), key=lambda kv: -len(kv[1])):
        etype = ph.strip("[]").rsplit("_", 1)[0]
        occ = [(a, b) for a, b in _occurrences(text, value)
               if not any(a < y and x < b for x, y in taken)]
        if not occ:
            continue
        entity = alias.get(ph, ph)
        if etype == "TÊN" and entity in seen_people:
            sugg = seen_people[entity]
        elif etype == "TÊN":
            g = _gender(text, mapping[entity], occ[0][0])
            letter = LETTERS[people % len(LETTERS)]
            people += 1
            sugg = {"m": f"Nguyễn Văn {letter}", "f": f"Nguyễn Thị {letter}"}.get(g, f"Người {letter}")
            seen_people[entity] = sugg
        elif etype == "TỔ_CHỨC":
            sugg = f"Công ty {ORG_LETTERS[orgs % len(ORG_LETTERS)]}"
            orgs += 1
        elif etype == "ĐỊA_CHỈ":
            sugg = "[địa chỉ]"
        else:
            sugg = "[số đã ẩn]"
        for a, b in occ:
            taken.append((a, b))
            spans.append(Span(id="", type=etype, group=GROUP.get(etype, "contact"), entity=entity,
                              text=text[a:b], start=a, end=b, suggestion=sugg,
                              default="pseudonym"))
    n = 0
    for m in _SENTENCE.finditer(text):
        if _SENSITIVE.search(m.group(0)):
            a = m.start() + len(m.group(0)) - len(m.group(0).lstrip())
            b = m.end()
            n += 1
            spans.append(Span(id="", type="TÌNH_TIẾT", group="sensitive_fact", entity=f"F{n}",
                              text=text[a:b], start=a, end=b,
                              suggestion="[tình tiết nhạy cảm, đã ẩn]", default="generalize"))
    spans.sort(key=lambda s: (s.start, -s.end))
    for i, s in enumerate(spans, 1):
        s.id = f"s{i}"
    return [asdict(s) for s in spans]


def apply(text: str, spans: list[dict], decisions: dict[str, dict] | None = None) -> dict:
    """Áp lựa chọn; trả {"text", "kept": số đoạn giữ nguyên, "counts": {loại: {action: n}}}.

    `decisions[span_id] = {"action": ..., "replacement": tuỳ chọn}`. Đoạn không có quyết định
    lấy mặc định. Tên giả nhất quán theo entity (đổi một đoạn là đổi cả người đó). Câu TÌNH_TIẾT
    bị làm chung chung thì nuốt luôn tên bên trong."""
    decisions = decisions or {}
    entity_repl: dict[str, str] = {}
    chosen = []
    for s in spans:
        d = decisions.get(s["id"]) or {}
        action = d.get("action") or s["default"]
        if action not in ACTIONS:
            raise ValueError(f"lựa chọn không hợp lệ: {action}")
        repl = d.get("replacement")
        if repl:
            entity_repl[s["entity"]] = repl
        chosen.append((s, action))
    edits = []
    blocked: list[tuple[int, int]] = []
    for s, action in chosen:  # câu tình tiết bị ẩn: chặn mọi đoạn bên trong
        if s["type"] == "TÌNH_TIẾT" and action != "keep":
            blocked.append((s["start"], s["end"]))
            edits.append((s["start"], s["end"], entity_repl.get(s["entity"], s["suggestion"])))
    counts: dict[str, dict[str, int]] = {}
    kept = 0
    for s, action in chosen:
        counts.setdefault(s["type"], {}).setdefault(action, 0)
        counts[s["type"]][action] += 1
        if action == "keep":
            kept += 1
            continue
        if s["type"] == "TÌNH_TIẾT":
            continue
        if any(a <= s["start"] and s["end"] <= b for a, b in blocked):
            continue
        edits.append((s["start"], s["end"], entity_repl.get(s["entity"], s["suggestion"])))
    # đoạn chồng lấn (tên công ty vắt sang câu tình tiết…): giữ đoạn đến trước, dài hơn
    accepted: list[tuple[int, int, str]] = []
    for a, b, r in sorted(edits, key=lambda e: (e[0], -(e[1] - e[0]))):
        if accepted and a < accepted[-1][1]:
            continue
        accepted.append((a, b, r))
    out = text
    for a, b, r in reversed(accepted):
        out = out[:a] + r + out[b:]
    return {"text": out, "kept": kept, "counts": counts}
