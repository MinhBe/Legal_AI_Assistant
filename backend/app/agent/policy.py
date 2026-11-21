"""Chính sách định tuyến của agent điều phối: khoá theo phiên bản, chỉ đổi khi qua cổng đo.

"Khoá tại một thời điểm rồi tự cải thiện":
1. Chính sách đang dùng là một tệp JSON có `version`, nằm trong eval/supervisor_policy.json.
2. Mỗi lần luật sư sửa định tuyến (vd. "đây là hợp đồng, phải rà soát"), phản hồi được lưu
   thành một dòng nhãn. `propose()` sinh chính sách ứng viên từ các dòng đó, bằng code.
3. `promote()` chạy cả hai chính sách trên bộ nhãn định tuyến (eval/routing_gold.jsonl
   + phản hồi). Ứng viên chỉ thay chính sách cũ khi đúng nhiều hơn và không làm sai ca nào
   chính sách cũ đã đúng. Không đạt thì giữ nguyên, ghi lý do.
Không gọi mô hình ở bước nào.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
POLICY_FILE = ROOT / "eval" / "supervisor_policy.json"
ROUTING_GOLD = ROOT / "eval" / "routing_gold.jsonl"


@dataclass
class Policy:
    version: int = 1
    contract_min_clauses: int = 3          # số dòng "Điều N" tối thiểu để coi là hợp đồng
    contract_words: list[str] = field(default_factory=lambda: [
        "hợp đồng lao động", "bên a", "bên b", "người sử dụng lao động", "các bên thoả thuận",
        "các bên thỏa thuận", "điều khoản"])
    draft_verbs: list[str] = field(default_factory=lambda: ["soạn", "viết giúp", "lập giúp", "làm giúp mẫu", "soạn thảo"])
    draft_objects: list[str] = field(default_factory=lambda: [
        "quyết định", "công văn", "thông báo", "tờ trình", "biên bản", "đơn", "hợp đồng"])
    calc_words: list[str] = field(default_factory=lambda: [
        "tính", "bao nhiêu tiền", "bao nhiêu ngày", "được bao nhiêu", "trợ cấp", "bồi thường bao nhiêu"])
    long_case_words: int = 60              # tình huống dài: tách vấn đề trước khi tra cứu

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Policy:
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load(path: Path = POLICY_FILE) -> Policy:
    try:
        return Policy.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return Policy()


def save(policy: Policy, path: Path = POLICY_FILE) -> None:
    path.write_text(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_rows(path: Path = ROUTING_GOLD) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def evaluate(policy: Policy, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Tỉ lệ ca có tập agent chính (contract/draft/calc/research) đúng như nhãn."""
    from app.agent.supervisor import primary_agents

    ok, wrong = 0, []
    for i, row in enumerate(rows):
        got = sorted(primary_agents(row["message"], policy))
        want = sorted(row["agents"])
        if got == want:
            ok += 1
        else:
            wrong.append({"i": i, "want": want, "got": got})
    n = len(rows)
    return {"n": n, "correct": ok, "accuracy": round(ok / n, 4) if n else None, "wrong": wrong}


def propose(current: Policy, feedback: list[dict[str, Any]]) -> Policy:
    """Ứng viên từ phản hồi: ca bị bỏ sót hợp đồng thì hạ ngưỡng số điều; ca bỏ sót soạn thảo
    thì thêm động từ đầu câu. Chỉ là đề xuất; `promote` quyết định có dùng hay không."""
    from app.agent.supervisor import count_clauses, primary_agents

    cand = deepcopy(current)
    cand.version = current.version + 1
    for row in feedback:
        want, got = set(row["agents"]), set(primary_agents(row["message"], current))
        if "contract" in want and "contract" not in got:
            n = count_clauses(row["message"])
            if 1 <= n < cand.contract_min_clauses:
                cand.contract_min_clauses = n
        if "draft" in want and "draft" not in got:
            first = row["message"].strip().lower().split()[:2]
            verb = " ".join(first)
            if verb and verb not in cand.draft_verbs:
                cand.draft_verbs.append(verb)
    return cand


def promote(current: Policy, candidate: Policy, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Cổng đo: ứng viên phải đúng nhiều hơn và không làm hỏng ca chính sách cũ đã đúng."""
    old, new = evaluate(current, rows), evaluate(candidate, rows)
    old_wrong = {w["i"] for w in old["wrong"]}
    broken = [w for w in new["wrong"] if w["i"] not in old_wrong]
    reasons = []
    if (new["accuracy"] or 0) <= (old["accuracy"] or 0):
        reasons.append(f"không tốt hơn: {new['accuracy']} ≤ {old['accuracy']}")
    if broken:
        reasons.append(f"làm sai {len(broken)} ca chính sách cũ đã đúng")
    return {"promoted": not reasons, "reasons": reasons, "current": old, "candidate": new,
            "policy": (candidate if not reasons else current).to_dict()}
