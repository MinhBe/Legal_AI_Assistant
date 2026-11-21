"""Agent điều phối nhiều tầng + chính sách định tuyến khoá theo phiên bản, có cổng đo."""

from __future__ import annotations

from app.agent import policy, supervisor
from app.agent.policy import Policy

CONTRACT = ("HỢP ĐỒNG LAO ĐỘNG\nBên A: Công ty X\nBên B: Nguyễn Văn A\n"
            "Điều 1. Công việc: kế toán\nĐiều 2. Thời hạn 48 tháng\nĐiều 3. Mức lương 4.000.000 đồng, vùng I")


def test_plan_routes_by_code():
    p = Policy()
    assert supervisor.primary_agents(CONTRACT, p) == ["contract"]
    assert supervisor.primary_agents("Soạn giúp quyết định khen thưởng", p) == ["draft"]
    assert supervisor.primary_agents("Nghỉ việc được trợ cấp bao nhiêu tiền?", p) == ["research", "calc"]
    pl = supervisor.plan("Ly hôn chia tài sản chung thế nào?", p)
    agents = [t["agent"] for t in pl["tasks"]]
    assert agents[0] == "research:hon_nhan_gia_dinh" and agents[-2:] == ["verifier", "risk"]
    assert {t["tier"] for t in pl["tasks"]} == {2, 3}


def test_contract_branch_needs_no_model():
    events = list(supervisor.run(CONTRACT))
    kinds = [e for e, _ in events]
    assert kinds[0] == "plan" and "contract_review" in kinds and kinds[-1] == "done"
    review = dict(events)["contract_review"]
    assert {"term_too_long", "below_min_wage"} <= {f["rule"] for f in review["findings"]}


def test_research_branch_wraps_answer_and_marks_agents():
    def fake_answer(message, history, use_uploads=False):
        yield ("step", {"name": "retrieve"})
        yield ("verify", {"ok": True})
        yield ("token", {"text": "Trả lời"})
        yield ("done", {"category": "law"})

    events = list(supervisor.run("Công ty nợ lương thì sao?", answer=fake_answer))
    agent_events = [d for e, d in events if e == "agent"]
    assert {"name": "verifier", "tier": 3, "status": "done"} in agent_events
    done = events[-1][1]
    assert done["category"] == "law" and "research:lao_dong" in done["agents"]


def test_locked_policy_baseline_on_routing_gold():
    rows = policy.load_rows()
    assert len(rows) >= 15
    res = policy.evaluate(policy.load(), rows)
    assert res["accuracy"] >= 0.9


def test_promote_only_when_better_and_nothing_breaks():
    current = Policy(contract_min_clauses=3)
    short_contract = "Hợp đồng lao động, bên a và bên b.\nĐiều 1. Lương 5.000.000 đồng\nĐiều 2. Thử việc 30 ngày"
    rows = [{"message": short_contract, "agents": ["contract"]},
            {"message": "Điều 35 BLLĐ quy định gì?", "agents": ["research"]}]
    cand = policy.propose(current, rows[:1])
    assert cand.version == 2 and cand.contract_min_clauses == 2
    res = policy.promote(current, cand, rows)
    assert res["promoted"] and res["candidate"]["accuracy"] == 1.0
    # ứng viên tệ hơn (bắt mọi thứ là hợp đồng) bị chặn
    bad = Policy(version=3, contract_min_clauses=1, contract_words=["điều"])
    blocked = policy.promote(cand, bad, rows)
    assert not blocked["promoted"] and blocked["policy"]["version"] == 2
