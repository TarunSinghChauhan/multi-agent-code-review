import pytest

from src.agents.state import CodeIssue
from src.agents.fix_proposal import fix_proposal_agent, FIX_TEMPLATES


def make_issue(issue_type, severity, title="Issue"):
    return CodeIssue(
        agent="security",
        issue_type=issue_type,
        severity=severity,
        line_number=1,
        title=title,
        description="desc",
    )


def make_state(issues):
    return {
        "job_id": "job_1",
        "filename": "app.py",
        "language": "python",
        "code": "",
        "issues": issues,
        "fix_proposals": [],
        "total_cost_usd": 0.0,
        "review_summary": "",
        "severity_counts": {},
        "completed": False,
    }


@pytest.mark.asyncio
async def test_generates_proposal_for_known_critical_issue():
    issues = [make_issue("hardcoded_password", "critical")]
    state = make_state(issues)
    result = await fix_proposal_agent(state)
    assert len(result["fix_proposals"]) == 1
    assert result["fix_proposals"][0].issue_title == "Issue"


@pytest.mark.asyncio
async def test_ignores_medium_and_low_severity_issues():
    issues = [
        make_issue("weak_hash", "medium"),
        make_issue("hardcoded_api_key", "low"),
    ]
    state = make_state(issues)
    result = await fix_proposal_agent(state)
    assert len(result["fix_proposals"]) == 0


@pytest.mark.asyncio
async def test_skips_unknown_issue_type():
    issues = [make_issue("some_unmapped_issue_type", "critical")]
    state = make_state(issues)
    result = await fix_proposal_agent(state)
    assert len(result["fix_proposals"]) == 0


@pytest.mark.asyncio
async def test_deduplicates_same_issue_type():
    issues = [
        make_issue("eval_usage", "high", title="First eval"),
        make_issue("eval_usage", "critical", title="Second eval"),
    ]
    state = make_state(issues)
    result = await fix_proposal_agent(state)
    assert len(result["fix_proposals"]) == 1
    assert result["fix_proposals"][0].issue_title == "First eval"


@pytest.mark.asyncio
async def test_caps_at_five_proposals():
    issue_types = list(FIX_TEMPLATES.keys())[:7]
    issues = [make_issue(t, "critical", title=t) for t in issue_types]
    state = make_state(issues)
    result = await fix_proposal_agent(state)
    assert len(result["fix_proposals"]) <= 5


@pytest.mark.asyncio
async def test_preserves_total_cost_usd():
    state = make_state([make_issue("hardcoded_password", "critical")])
    state["total_cost_usd"] = 0.42
    result = await fix_proposal_agent(state)
    assert result["total_cost_usd"] == 0.42


@pytest.mark.asyncio
async def test_no_issues_returns_empty_proposals():
    state = make_state([])
    result = await fix_proposal_agent(state)
    assert result["fix_proposals"] == []
