from unittest.mock import AsyncMock, patch

import pytest

from src.agents.orchestrator import _check_cost_budget, _run_parallel_agents
from src.agents.state import CodeIssue


def make_state(total_cost_usd=0.0):
    return {
        "job_id": "job_1",
        "filename": "app.py",
        "language": "python",
        "code": "",
        "issues": [],
        "fix_proposals": [],
        "total_cost_usd": total_cost_usd,
        "review_summary": "",
        "severity_counts": {},
        "completed": False,
    }


def test_check_cost_budget_routes_to_fix_when_under_budget(monkeypatch):
    from src.agents import orchestrator
    monkeypatch.setattr(orchestrator.settings, "max_cost_per_review_usd", 0.50)
    state = make_state(total_cost_usd=0.10)
    assert _check_cost_budget(state) == "fix"


def test_check_cost_budget_routes_to_merge_when_over_budget(monkeypatch):
    from src.agents import orchestrator
    monkeypatch.setattr(orchestrator.settings, "max_cost_per_review_usd", 0.50)
    state = make_state(total_cost_usd=0.75)
    assert _check_cost_budget(state) == "merge"


def test_check_cost_budget_routes_to_merge_exactly_at_budget(monkeypatch):
    from src.agents import orchestrator
    monkeypatch.setattr(orchestrator.settings, "max_cost_per_review_usd", 0.50)
    state = make_state(total_cost_usd=0.50)
    assert _check_cost_budget(state) == "merge"


@pytest.mark.asyncio
async def test_run_parallel_agents_merges_issues_from_both_agents():
    state = make_state()
    fake_issue_1 = CodeIssue(agent="static_analysis", issue_type="bare_except", severity="medium", title="t", description="d")
    fake_issue_2 = CodeIssue(agent="security", issue_type="eval_usage", severity="high", title="t2", description="d2")

    with patch("src.agents.orchestrator.static_analysis_agent", new=AsyncMock(return_value={"issues": [fake_issue_1], "total_cost_usd": 0.01})), \
         patch("src.agents.orchestrator.security_agent", new=AsyncMock(return_value={"issues": [fake_issue_2], "total_cost_usd": 0.02})):
        result = await _run_parallel_agents(state)

    assert len(result["issues"]) == 2
    assert result["total_cost_usd"] == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_run_parallel_agents_skips_failed_agent_without_crashing():
    state = make_state()
    fake_issue = CodeIssue(agent="security", issue_type="eval_usage", severity="high", title="t", description="d")

    with patch("src.agents.orchestrator.static_analysis_agent", new=AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("src.agents.orchestrator.security_agent", new=AsyncMock(return_value={"issues": [fake_issue], "total_cost_usd": 0.02})):
        result = await _run_parallel_agents(state)

    assert len(result["issues"]) == 1
    assert result["issues"][0].issue_type == "eval_usage"
