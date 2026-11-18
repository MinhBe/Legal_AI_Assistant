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
3. When sources disagree on MEANING (e.g. "tách được" vs "không tách được") or on a NUMBER or \
CITATION (e.g. 109 vs 129): if three sources exist and two agree, take the majority; \
otherwise write both as [?a/b], e.g. [?109/129]. Never pick silently, never invent.
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
- "facts" and "lawyer_says" contain only what is in the transcript. Never add events, people, \
amounts or conclusions.
- Everything you add yourself goes to "suggestions", each with "needs_lawyer_review": true.
- NEVER output an article/law/decree number that is not in the transcript, unless it is in \
the corpus list given to you. A citation from your own memory must have status \
"outside_corpus_unverified" and source "model". Only use "verified_in_corpus" for documents \
in the corpus list.
- Keep [?a/b] and [?] marks; list them under "uncertain". Do not resolve them.
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
                try:
                    units.append(Unit.model_validate(item).model_dump())
                except ValidationError as exc:
                    errors.append(f"unit: {exc.errors()[0]['msg']}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"stage2: {str(exc)[:200]}")
    return {"corrected": corrected, "units": units, "errors": errors}


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
        for said in u["lawyer_says"]:
            for n in _numbers(said):
                if n not in allowed:
                    issues.append(f"unit {i}: lawyer_says có số {n} không có trong nguồn")
    return issues
