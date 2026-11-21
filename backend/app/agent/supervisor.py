"""Agent điều phối nhiều tầng (chế độ chat "agents").

Tầng 1, điều phối: đọc câu bằng code, lập kế hoạch giao việc. Không gọi mô hình.
Tầng 2, chuyên trách:
  - contract: rà soát hợp đồng bằng luật code (app.contract.review)
  - research:<lĩnh vực>: tra cứu + trả lời có trích dẫn (app.agent.qa), mỗi lĩnh vực một nhánh
  - calc: máy tính lao động, chạy trong nhánh tra cứu qua bảng tình tiết
  - draft: chỉ đường tới soạn văn bản/biểu mẫu
Tầng 3, kiểm soát: kiểm trích dẫn bằng code (verifier, trong nhánh tra cứu), chấm rủi ro
  và chuyển luật sư (app.agent.risk) — dùng lại các bước có sẵn.

Mỗi bước phát sự kiện ("plan" / "agent") để giao diện vẽ ai đang làm gì.
Chính sách định tuyến khoá theo phiên bản (app.agent.policy), chỉ đổi khi qua cổng đo.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

from app.agent.policy import Policy, load
from app.rag import domain

_CLAUSE_LINE = re.compile(r"(?im)^\s*điều\s+\d+")


def count_clauses(message: str) -> int:
    return len(_CLAUSE_LINE.findall(message or ""))


def _has_any(text: str, words: list[str]) -> bool:
    return any(w in text for w in words)


def is_contract(message: str, policy: Policy) -> bool:
    t = (message or "").lower()
    return count_clauses(message) >= policy.contract_min_clauses and _has_any(t, policy.contract_words)


def is_draft(message: str, policy: Policy) -> bool:
    t = (message or "").lower()
    return _has_any(t, policy.draft_verbs) and _has_any(t, policy.draft_objects)


def is_calc(message: str, policy: Policy) -> bool:
    return _has_any((message or "").lower(), policy.calc_words)


def primary_agents(message: str, policy: Policy | None = None) -> list[str]:
    """Các agent tầng 2 chính (không tính lĩnh vực) — dùng cho cổng đo định tuyến."""
    policy = policy or load()
    if is_contract(message, policy):
        return ["contract"]
    if is_draft(message, policy):
        return ["draft"]
    agents = ["research"]
    if is_calc(message, policy):
        agents.append("calc")
    return agents


def plan(message: str, policy: Policy | None = None) -> dict[str, Any]:
    policy = policy or load()
    agents = primary_agents(message, policy)
    tasks: list[dict[str, Any]] = []
    if "contract" in agents:
        tasks.append({"agent": "contract", "tier": 2, "label": "Rà soát hợp đồng",
                      "why": f"có {count_clauses(message)} dòng \"Điều N\" và từ ngữ hợp đồng"})
    elif "draft" in agents:
        tasks.append({"agent": "draft", "tier": 2, "label": "Soạn văn bản", "why": "yêu cầu soạn văn bản"})
    else:
        doms = domain.classify(message)
        for d in doms:
            tasks.append({"agent": f"research:{d}", "tier": 2, "label": f"Tra cứu {domain.label(d)}",
                          "why": "lĩnh vực nhận ra từ từ khoá"})
        if len(message.split()) >= policy.long_case_words:
            tasks[0]["split_issues"] = True
        if "calc" in agents:
            tasks.append({"agent": "calc", "tier": 2, "label": "Tính toán", "why": "câu hỏi cần con số"})
        tasks.append({"agent": "verifier", "tier": 3, "label": "Kiểm trích dẫn", "why": "mọi câu trả lời có căn cứ"})
        tasks.append({"agent": "risk", "tier": 3, "label": "Chấm rủi ro, chuyển luật sư khi cần",
                      "why": "ca khó cần người duyệt"})
    return {"supervisor": "điều phối", "policy_version": policy.version, "tasks": tasks}


def _agent(name: str, tier: int, status: str, **extra: Any) -> tuple[str, dict]:
    return ("agent", {"name": name, "tier": tier, "status": status, **extra})


def run(message: str, history: list[dict[str, str]] | None = None, *, use_uploads: bool = False,
        answer=None) -> Iterator[tuple[str, object]]:
    """`answer` = hàm tra cứu (mặc định app.agent.qa.answer_with_citations); test thay được."""
    p = plan(message)
    yield ("plan", p)
    first = p["tasks"][0]["agent"]

    if first == "contract":
        from app.contract.review import check

        yield _agent("contract", 2, "start")
        result = check(message)
        yield ("contract_review", result)
        c = result["counts"]
        yield ("token", {"text": (
            f"Đã rà soát hợp đồng: {c['high']} điểm trái luật, {c['medium']} điểm cần sửa, {c['low']} lưu ý. "
            "Chi tiết từng điểm kèm căn cứ ở bảng rà soát.")})
        yield _agent("contract", 2, "done", verdict=result["verdict"])
        yield ("done", {"category": "contract_review", "agents": ["contract"]})
        return

    if first == "draft":
        yield _agent("draft", 2, "start")
        yield ("route", {"href": "/bieu-mau", "label": "Mở thư viện biểu mẫu và soạn văn bản"})
        yield ("token", {"text": "Yêu cầu soạn văn bản: mở mục Biểu mẫu để chọn mẫu đã khoá rồi điền theo vụ việc."})
        yield _agent("draft", 2, "done")
        yield ("done", {"category": "draft", "agents": ["draft"]})
        return

    if answer is None:
        from app.agent.qa import answer_with_citations as answer

    research = [t["agent"] for t in p["tasks"] if t["agent"].startswith("research:")]
    for name in research:
        yield _agent(name, 2, "start")
    # Nhánh tra cứu đã gồm tách vấn đề, bảng tình tiết + máy tính, kiểm trích dẫn, chấm rủi ro.
    for event, data in answer(message, history or [], use_uploads=use_uploads):
        if event == "verify":
            yield _agent("verifier", 3, "done")
        if event == "calculations":
            yield _agent("calc", 2, "done")
        if event == "done":
            for name in research:
                yield _agent(name, 2, "done")
            data = {**(data or {}), "agents": [t["agent"] for t in p["tasks"]]}
        yield event, data
