"""Bản chép lời tư vấn -> đơn vị hỏi–đáp có cấu trúc (prompt v2 của Tech Lead, 18/11/2026).

Ba bước, mỗi bước một lời gọi mô hình:
1. RECONCILE + CORRECT: gộp bản PhoWhisper (chính) với bản lượt hai / bản thứ ba, sửa thuật
   ngữ pháp lý bị nghe nhầm, viết số bằng chữ số, chỗ hai bản vênh về nghĩa/số thì đánh
   dấu [?a/b] thay vì đoán.
2+3. SEGMENT + EXTRACT: tách thành đơn vị hỏi–đáp và trả JSON theo lược đồ.

Đầu vào luôn là bản ĐÃ CHE PII. `audit` kiểm bằng code các luật cứng: không có số điều nào
mà nguồn không nói; trích dẫn "verified_in_corpus" phải có thật trong kho.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.llm.router import parse_json

KNOWN_FIXES = (
    "lợi sư -> luật sư; hành trí -> hành chính; hành sự -> hình sự (when about criminal "
    "liability) or hành chính (when about administrative fines); phóng trứng -> văn phòng công "
    "chứng; khoản môn / khoảng một -> khoản 1; 'điều ba trên hai mốt' -> Điều 321; môn hình sự / "
    "mô lĩnh sự / bồ lảnh sự -> Bộ luật Hình sự; nụt -> nộp; khu nhập -> thu nhập; giả soát -> rà "
    "soát; tính lương tìm công / tiền lớn tìm công -> tiền lương, tiền công; triệu thuế -> chịu "
    "thuế; thấu trừ -> khấu trừ; i tách / e-tex -> eTax; quyền sở đất / quyền sử đất -> quyền sử "
    "dụng đất; tách hửa -> tách thửa; số đỏ -> sổ đỏ; đất ẩm -> đất ở"
)

STAGE1_SYSTEM = f"""You clean up automatic speech transcripts of Vietnamese legal \
consultations (livestreams, TV Q&A, phone calls). Personal data is already masked as \
placeholders like [TÊN_1], [TỔ_CHỨC_2], [SĐT_1]; copy placeholders exactly, never guess who \
they are.

You receive the same audio window from several recognisers:
- SOURCE A = PhoWhisper (primary: best Vietnamese vocabulary, but lowercase, no punctuation, \
numbers spelled out, weak on article/law numbers);
- SOURCE B / SOURCE C = Whisper (punctuation and digits, but mishears legal words).

Write ONE corrected Vietnamese transcript:
1. Fix misheard legal terms. Known pairs: {KNOWN_FIXES}.
2. Add punctuation and capitalisation; write numbers, amounts, dates, article and law numbers \
as digits ("Điều 321", "5 triệu", "109/2025").
3. Disagreements between sources:
   - MEANING words (e.g. "tách được" vs "không tách được"): if three sources exist and two \
agree, take the majority; with only two sources, write both: [?tách được/không tách được].
   - NUMBERS in law/decree/article citations (law number, decree number, Điều, khoản): \
B and C come from the same recogniser family, so a majority does NOT settle them. Keep \
[?109/129] unless ALL sources agree.
   - Write the real alternatives inside the brackets. Never write the literal text "[?a/b]".
   - Never pick silently, never invent.
4. Keep the speakers' meaning and wording; do not summarise. Mark words you cannot \
reconstruct as [?].
5. Drop advertising, channel promotion, greetings and calls to comment.
6. Start each sentence group with its timestamp from the sources, as [mm:ss] or [hh:mm:ss].

Return only JSON: {{"corrected": "<the corrected transcript>"}}"""

UNIT_SCHEMA = """{"units": [{
  "domain": "<lao động | đất đai | hôn nhân gia đình | hình sự | xử phạt hành chính | thuế TNCN | dân sự | khác>",
  "in_scope_labour": "<yes | related | no>",
  "facts": ["<facts as the asker/speaker stated them>"],
  "legal_question": "<the legal question to answer>",
  "lawyer_says": ["<ONLY what the lawyer/expert actually said, faithful, no additions>"],
  "suggestions": [{"text": "<your addition the lawyer did not say>", "needs_lawyer_review": true}],
  "citations": [{"doc": "<document name>", "article": "<Điều X khoản Y or empty>",
                 "status": "<verified_in_corpus | outside_corpus_unverified>",
                 "source": "<audio | model>"}],
  "practical_tactics": ["<lawful practical steps only>"],
  "uncertain": ["<doubtful hearing, [?a/b] marks, missing facts, cut-off speech>"],
  "start": "<mm:ss>", "end": "<mm:ss>"
}]}"""

FEW_SHOT_INPUT = """[01:55] Câu hỏi tiếp theo: Luật sư cho cháu hỏi nhờ đánh đề có bị phạt không ạ?
[02:01] Chắc chắn là sẽ bị xử lý bạn nhé. Hành vi đánh đề bản chất là đánh bạc, được quy vào \
tội đánh bạc. Tùy theo tính chất mức độ thì có thể bị xử phạt hành chính hoặc bị xử lý hình sự.
[02:18] Về hành chính, nếu một lần chơi mà không đến 5 triệu, ví dụ bạn đánh dưới 5 triệu mà \
không trúng, thì bạn sẽ bị xử phạt hành chính, bởi vì số tiền chơi chưa đến 5 triệu.
[02:34] Còn nếu bạn đánh mà trúng, ví dụ đánh 5 triệu mà trúng thành 20–25 triệu, trường hợp \
như vậy là đủ số tiền để khởi tố về tội đánh bạc theo quy định tại khoản 1 Điều 321 Bộ luật \
Hình sự. Bạn nhờ đánh hay bạn trực tiếp đánh thì bản chất vẫn là hành vi đánh bạc."""

FEW_SHOT_OUTPUT = {
    "units": [{
        "domain": "hình sự",
        "in_scope_labour": "no",
        "facts": ["Người hỏi nhờ người khác đánh đề (cá cược theo kết quả xổ số)."],
        "legal_question": "Nhờ người khác đánh đề có bị xử phạt không; khi nào bị xử lý hình sự?",
        "lawyer_says": [
            "Đánh đề bản chất là đánh bạc.",
            "Số tiền chơi dưới 5 triệu đồng thì bị xử phạt hành chính.",
            "Từ 5 triệu đồng trở lên thì đủ yếu tố khởi tố theo khoản 1 Điều 321 Bộ luật Hình sự.",
            "Số tiền tính cả tiền trúng (đánh 5 triệu trúng 20–25 triệu là đủ để khởi tố).",
            "Nhờ đánh hay tự đánh đều là hành vi đánh bạc.",
        ],
        "suggestions": [
            {"text": "Dưới 5 triệu đồng vẫn có thể bị truy cứu nếu đã bị xử phạt hành chính về "
                     "hành vi này hoặc đã bị kết án về tội này, chưa được xoá án tích.",
             "needs_lawyer_review": True},
            {"text": "Cách tính số tiền dùng đánh bạc cần đối chiếu hướng dẫn hiện hành của Hội "
                     "đồng Thẩm phán TANDTC.", "needs_lawyer_review": True},
            {"text": "Mức phạt hành chính cụ thể theo nghị định xử phạt hiện hành; cần tra văn "
                     "bản đang có hiệu lực.", "needs_lawyer_review": True},
        ],
        "citations": [
            {"doc": "Bộ luật Hình sự", "article": "khoản 1 Điều 321",
             "status": "outside_corpus_unverified", "source": "audio"},
        ],
        "practical_tactics": [
            "Không tham gia đánh đề dưới mọi hình thức, kể cả nhờ người khác đánh hộ.",
            "Nếu đã bị mời làm việc, nên có luật sư tham gia và trình bày trung thực.",
        ],
        "uncertain": ["Bản ghi không nói rõ người hỏi đã từng bị xử phạt hay có án tích chưa."],
        "start": "01:55", "end": "03:00",
    }]
}

STAGE2_SYSTEM = f"""You turn a corrected Vietnamese legal-consultation transcript into \
structured Q&A units for lawyers to review. Personal data is masked ([TÊN_1] …); copy \
placeholders as they are and never try to identify anyone.

Steps: split the transcript into Q&A units (one per question the lawyer/expert answers; \
skip intros, ads, greetings); then fill this JSON schema per unit, in Vietnamese:
{UNIT_SCHEMA}

Hard rules:
- "facts" are the asker's situation only (not the lawyer's answer), as stated. No \
calculations or inferences (do not write "each child gets 100 m²").
- "lawyer_says" contains only what the lawyer/expert said, without repeats. Never add events, \
people, amounts or conclusions.
- A new question from the host or asker starts a new unit, even if the same expert answers.
- Everything you add yourself goes to "suggestions", each with "needs_lawyer_review": true.
- NEVER output an article/law/decree number that is not in the transcript, unless it is in \
the corpus list given to you. This applies to suggestions too.
- A document you add from memory: give only its name with NO article number, status \
"outside_corpus_unverified", source "model". Today is 2026: cite the version in force \
(e.g. Luật Đất đai 2024, not 2013; Bộ luật Lao động 2019, not 2012). Do not mention abolished \
papers such as sổ hộ khẩu.
- A citation spoken in the audio has source "audio". Only use "verified_in_corpus" for \
documents in the corpus list.
- Keep every [?x/y] and [?] mark exactly, in the field where it occurs AND under \
"uncertain" with a short explanation. Do not resolve them.
- DURATIONS / DEADLINES: when the lawyer gives a processing time that differs from the legal \
maximum you can see in the corpus, do NOT call it an error or a discrepancy. Lawyers often give \
a shorter, experience-based planning figure because of delays, cumbersome procedures or \
sensitive cases. Put both in "suggestions": (a) the practical recommendation = the lawyer's \
figure and why to plan with it, and (b) the legal maximum with its exact citation (e.g. \
"NĐ 101/2024/NĐ-CP Điều 22 khoản 4: không quá 15 ngày làm việc"), plus what to do if the office \
exceeds the legal maximum (ask for the reason in writing, request a new appointment slip, then \
complain). Set needs_lawyer_review true ONLY when the lawyer's figure is LONGER than the legal \
maximum in a way that suggests outdated law.
- All values are strings (or lists of strings); "start"/"end" are "mm:ss" strings.
- Do not repeat the same sentence in suggestions and practical_tactics.
- "practical_tactics": lawful steps only. Never give tips for evading the law, hiding assets, \
avoiding detection or obstructing authorities.
- "in_scope_labour": "yes" for labour law, "related" when it touches wages/employment \
(e.g. PIT on salary), otherwise "no".

Example input:
{FEW_SHOT_INPUT}

Example output:
{json.dumps(FEW_SHOT_OUTPUT, ensure_ascii=False)}

Return only the JSON object."""


class Suggestion(BaseModel):
    text: str
    needs_lawyer_review: bool = True


class Citation(BaseModel):
    doc: str
    article: str = ""
    status: str = "outside_corpus_unverified"
    source: str = "model"


class Unit(BaseModel):
    domain: str
    in_scope_labour: str = "no"
    facts: list[str] = Field(default_factory=list)
    legal_question: str = ""
    lawyer_says: list[str] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    practical_tactics: list[str] = Field(default_factory=list)
    uncertain: list[str] = Field(default_factory=list)
    start: str = ""
    end: str = ""


def _coerce(item: dict[str, Any]) -> None:
    """Sửa lệch kiểu hay gặp (MiniMax): số ở trường chuỗi, gợi ý là chuỗi trần, phần tử
    danh sách là dict… Không đổi nội dung, chỉ đổi kiểu để kiểm lược đồ không vứt cả đơn vị."""
    for key in ("domain", "in_scope_labour", "legal_question", "start", "end"):
        if item.get(key) is not None and not isinstance(item[key], str):
            item[key] = str(item[key])
    for key in ("facts", "lawyer_says", "practical_tactics", "uncertain"):
        val = item.get(key)
        if isinstance(val, str):
            val = [val]
        if isinstance(val, list):
            item[key] = [v.get("text", json.dumps(v, ensure_ascii=False)) if isinstance(v, dict)
                         else str(v) for v in val]
    sugg = item.get("suggestions")
    if isinstance(sugg, list):
        item["suggestions"] = [{"text": s, "needs_lawyer_review": True} if isinstance(s, str)
                               else s for s in sugg]
    cites = item.get("citations")
    if isinstance(cites, list):
        fixed = []
        for c in cites:
            entry = {"doc": c} if isinstance(c, str) else c
            if isinstance(entry, dict):
                fixed.append({k: "" if v is None else str(v) for k, v in entry.items()})
        item["citations"] = fixed


def stage1_user(sources: dict[str, str]) -> str:
    return "\n\n".join(f"SOURCE {name}:\n{text}" for name, text in sources.items())


def stage2_user(corrected: str, corpus_docs: list[str]) -> str:
    docs = "; ".join(corpus_docs) if corpus_docs else "(none)"
    return f"Corpus documents (labour law): {docs}\n\nTranscript:\n{corrected}"


def run(
    call: Callable[[list[dict[str, str]]], str],
    sources: dict[str, str],
    corpus_docs: list[str],
) -> dict[str, Any]:
    """Chạy hai lời gọi; trả {"corrected", "units", "errors"}. `call` nhận messages, trả text."""
    errors: list[str] = []
    corrected = ""
    try:
        data = parse_json(call([{"role": "system", "content": STAGE1_SYSTEM},
                                {"role": "user", "content": stage1_user(sources)}]))
        corrected = str(data.get("corrected") or "")
    except Exception as exc:  # noqa: BLE001 — ghi lỗi, không làm hỏng cả lượt so sánh
        errors.append(f"stage1: {str(exc)[:200]}")
    units: list[dict[str, Any]] = []
    if corrected:
        try:
            data = parse_json(call([{"role": "system", "content": STAGE2_SYSTEM},
                                    {"role": "user", "content": stage2_user(corrected, corpus_docs)}]))
            for item in data.get("units") or []:
                if isinstance(item, dict):
                    _coerce(item)
                try:
                    units.append(Unit.model_validate(item).model_dump())
                except ValidationError as exc:
                    errors.append(f"unit: {exc.errors()[0]['msg']}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"stage2: {str(exc)[:200]}")
    return {"corrected": corrected, "units": units, "errors": errors}


def enforce(result: dict[str, Any], corpus_docs: list[str]) -> list[str]:
    """Lưới an toàn bằng code trước khi lưu vào /bai-toan (mô hình nhỏ hay vi phạm):
    - "verified_in_corpus" cho văn bản ngoài kho -> hạ về "outside_corpus_unverified";
    - trích dẫn từ trí nhớ (source=model) có số điều -> xoá số điều;
    - mọi gợi ý luôn needs_lawyer_review=True.
    Trả danh sách thay đổi (ghi kèm để luật sư biết mô hình đã vi phạm gì)."""
    changes: list[str] = []
    corpus = [d.lower() for d in corpus_docs]
    for i, u in enumerate(result.get("units", []), 1):
        for c in u["citations"]:
            in_corpus = any(d in c["doc"].lower() or c["doc"].lower() in d for d in corpus)
            if c["status"] == "verified_in_corpus" and not in_corpus:
                c["status"] = "outside_corpus_unverified"
                changes.append(f"unit {i}: hạ '{c['doc']}' về outside_corpus_unverified")
            if c["source"] == "model" and re.search(r"\d", c["article"]):
                changes.append(f"unit {i}: xoá số điều từ trí nhớ '{c['article']}'")
                c["article"] = ""
        for s in u["suggestions"]:
            # ghi chú thời hạn (mức nên dự trù theo luật sư + mức tối đa luật định) là thông tin
            # thủ tục, Minh duyệt 19/11/2026 không cần luật sư duyệt lại; mọi gợi ý khác thì cần
            if not (s.get("needs_lawyer_review") is False and is_deadline_note(s["text"])):
                s["needs_lawyer_review"] = True
    return changes


_DEADLINE = re.compile(r"tối đa|không quá", re.IGNORECASE)
_WORKDAYS = re.compile(r"\d+\s*ngày(?:\s+làm việc)?", re.IGNORECASE)


def is_deadline_note(text: str) -> bool:
    """Gợi ý dạng "nên dự trù N ngày (luật sư) — tối đa M ngày làm việc theo … Điều …"."""
    return bool(_DEADLINE.search(text) and _WORKDAYS.search(text)
                and re.search(r"Điều\s+\d+", text))


_NUM = re.compile(r"\d+(?:/\d+)*")


def _numbers(text: str) -> set[str]:
    return set(_NUM.findall(text))


def audit(result: dict[str, Any], source_text: str, corpus_docs: list[str]) -> list[str]:
    """Kiểm bằng code các luật cứng; trả danh sách vi phạm (rỗng là đạt).

    - số điều/văn bản trong trích dẫn hoặc lời luật sư mà không có trong các bản nguồn
      (số trong nguồn có thể viết bằng chữ, nên so với bản đã sửa ở bước 1 nữa);
    - "verified_in_corpus" cho văn bản không có trong kho.
    """
    issues: list[str] = []
    allowed = _numbers(source_text) | _numbers(result.get("corrected", ""))
    corpus = [d.lower() for d in corpus_docs]
    for i, u in enumerate(result.get("units", []), 1):
        for c in u["citations"]:
            for n in _numbers(f"{c['article']} {c['doc']}"):
                if n not in allowed and c["source"] == "audio":
                    issues.append(f"unit {i}: số {n} trong trích dẫn không có trong nguồn")
            if c["status"] == "verified_in_corpus" and not any(
                d in c["doc"].lower() or c["doc"].lower() in d for d in corpus
            ):
                issues.append(f"unit {i}: '{c['doc']}' ghi verified_in_corpus nhưng không có trong kho")
            if c["source"] == "model" and re.search(r"\d", c["article"]):
                issues.append(f"unit {i}: trích dẫn từ trí nhớ có số điều '{c['article']}'")
        for said in u["lawyer_says"]:
            for n in _numbers(said):
                if n not in allowed:
                    issues.append(f"unit {i}: lawyer_says có số {n} không có trong nguồn")
        for s in u["suggestions"]:
            for m in re.finditer(r"(?:Điều|khoản|Nghị định|số)\s+(\d+(?:/\d+)*)", s["text"]):
                if m[1] not in allowed:
                    issues.append(f"unit {i}: gợi ý nêu '{m[0]}' không có trong nguồn")
    if "[?a/b]" in json.dumps(result, ensure_ascii=False):
        issues.append("còn chữ '[?a/b]' nguyên văn thay vì hai khả năng thật")
    return issues
