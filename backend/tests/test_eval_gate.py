"""Contract G4 — cổng đánh giá không gọi LLM. Thuần Python + một nhóm cần DB."""

from __future__ import annotations

import pytest

from app.eval.gate import compare

PASSING = {
    "recall@5": {"value": 0.80, "n": 10, "n_reviewed": 0, "errors": 2, "bound": None},
    "recall@8": {"value": 0.90, "n": 10, "n_reviewed": 0, "errors": 1, "bound": None},
    "mrr": {"value": 0.70, "n": 10, "n_reviewed": 0, "errors": None, "bound": None},
    "version_correct": {"value": 1.0, "n": 10, "n_reviewed": 0, "errors": 0, "bound": 0.3},
    "injection_block": {"value": 1.0, "n": 5, "n_reviewed": 0, "errors": 0, "bound": 0.6},
    "pii_leak": {"value": 0, "n": 20, "n_reviewed": 0, "errors": 0, "bound": 0.15},
    "upload_isolation": {"value": True, "n": 5, "n_reviewed": 0, "errors": 0, "bound": 0.6},
}


def _variant(**changes) -> dict:
    out = {k: dict(v) for k, v in PASSING.items()}
    for name, value in changes.items():
        out[name]["value"] = value
    return out


def test_compare_accepts_matching_baseline():
    assert compare(PASSING, PASSING) == []


def test_compare_flags_three_point_recall_drop():
    fails = compare(_variant(**{"recall@5": 0.77}), PASSING)
    assert len(fails) == 1 and "recall@5" in fails[0]


def test_compare_accepts_one_point_drop():
    assert compare(_variant(**{"recall@5": 0.79, "mrr": 0.69}), PASSING) == []


def test_compare_flags_pii_leak():
    fails = compare(_variant(pii_leak=1), PASSING)
    assert any("pii_leak" in f for f in fails)


def test_compare_flags_upload_isolation_false():
    fails = compare(_variant(upload_isolation=False), PASSING)
    assert any("upload_isolation" in f for f in fails)


def test_compare_accepts_baseline_file_shape():
    assert compare(PASSING, {"date": "2026-01-01", "metrics": PASSING}) == []


# ── DB ────────────────────────────────────────────────────────────────────────

@pytest.mark.db
def test_run_gate_returns_all_metrics(db):
    from app.eval.gate import run_gate

    metrics = run_gate(db)
    assert set(metrics) == {
        "recall@5", "recall@8", "mrr", "version_correct",
        "injection_block", "pii_leak", "upload_isolation",
    }
    for name, m in metrics.items():
        assert m["n"] > 0, name
        assert m["value"] is not None, name
    assert metrics["pii_leak"]["value"] == 0
    assert metrics["upload_isolation"]["value"] is True
