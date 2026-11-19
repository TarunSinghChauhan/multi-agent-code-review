"""A review that could not finish must not read as a clean bill of health."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents import security, static_analysis
from src.agents.merger import merger_agent
from src.agents.orchestrator import CodeReviewOrchestrator, _run_parallel_agents
from src.agents.state import CodeIssue
from src.api.routers.reviews import serialize_result


def issue(severity="high", **kw):
    base = dict(agent="security", issue_type="sqli", severity=severity, line_number=1,
                title="t", description="d")
    base.update(kw)
    return CodeIssue(**base)


def state(issues=(), **extra):
    s = {
        "job_id": "j", "filename": "app.py", "language": "python", "code": "x = 1\n",
        "issues": list(issues), "fix_proposals": [], "total_cost_usd": 0.0,
        "review_summary": "", "severity_counts": {}, "completed": False,
    }
    s.update(extra)
    return s


# ---- merger -----------------------------------------------------------------------

def test_no_issues_and_no_warnings_is_still_lgtm():
    out = merger_agent(state())
    assert "LGTM" in out["review_summary"]
    assert out["warnings"] == []


def test_no_issues_with_a_warning_is_not_lgtm():
    out = merger_agent(state(warnings=["security: agent crashed; none of its findings are included"]))
    assert "LGTM" not in out["review_summary"]
    assert "INCOMPLETE REVIEW" in out["review_summary"]
    assert "security: agent crashed" in out["review_summary"]


def test_a_critical_finding_keeps_its_verdict_and_still_lists_the_warning():
    out = merger_agent(state([issue("critical")], warnings=["static_analysis: agent crashed"]))
    assert "Do not merge" in out["review_summary"]
    assert "Incomplete review" in out["review_summary"]


def test_minor_issues_with_a_warning_still_mention_incompleteness():
    out = merger_agent(state([issue("low")], warnings=["x"]))
    assert "Incomplete review" in out["review_summary"]


def test_state_without_a_warnings_key_still_works():
    assert "LGTM" in merger_agent(state())["review_summary"]


# ---- agents -----------------------------------------------------------------------

def reply(content="[]"):
    r = MagicMock()
    r.choices = [MagicMock(message=MagicMock(content=content))]
    r.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    return r


LONG_CODE = "x = 1\n" * 600  # about 3600 characters: two pieces for the LLM
CASES = [(security, security.security_agent), (static_analysis, static_analysis.static_analysis_agent)]


@pytest.mark.asyncio
@pytest.mark.parametrize("module,agent", CASES)
async def test_a_failed_llm_piece_becomes_a_warning_and_the_other_piece_is_kept(module, agent, monkeypatch):
    monkeypatch.setattr(module.settings, "llm_enabled", True)
    ok = reply(json.dumps([{"issue_type": "x", "severity": "low", "line_number": 1, "title": "kept"}]))
    client = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=[RuntimeError("secret-key-123 rejected"), ok])
    with patch.object(module, "_get_client", return_value=client):
        result = await agent(state(code=LONG_CODE))
    assert [i.title for i in result["issues"] if i.issue_type == "x"] == ["kept"]
    assert len(result["warnings"]) == 1
    assert "starting at line 1" in result["warnings"][0]
    assert "secret-key-123" not in result["warnings"][0]   # provider error text stays in the log


@pytest.mark.asyncio
@pytest.mark.parametrize("module,agent", CASES)
async def test_an_unparseable_reply_is_a_warning_too(module, agent, monkeypatch):
    monkeypatch.setattr(module.settings, "llm_enabled", True)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply("not json"))
    with patch.object(module, "_get_client", return_value=client):
        result = await agent(state())
    assert len(result["warnings"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("module,agent", CASES)
async def test_a_clean_run_has_no_warnings(module, agent, monkeypatch):
    monkeypatch.setattr(module.settings, "llm_enabled", True)
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply("[]"))
    with patch.object(module, "_get_client", return_value=client):
        result = await agent(state())
    assert result["warnings"] == []


# ---- orchestrator -----------------------------------------------------------------

@pytest.mark.asyncio
async def test_a_crashed_agent_is_reported_by_name_and_the_other_agents_issues_are_kept():
    from src.agents import orchestrator
    good = {"issues": [issue("low", agent="static_analysis")], "total_cost_usd": 0.0, "warnings": []}
    with patch.object(orchestrator, "static_analysis_agent", AsyncMock(return_value=good)), \
         patch.object(orchestrator, "security_agent", AsyncMock(side_effect=RuntimeError("boom"))):
        merged = await _run_parallel_agents(state())
    assert len(merged["issues"]) == 1
    assert merged["warnings"] == ["security: agent crashed; none of its findings are included"]


@pytest.mark.asyncio
async def test_warnings_from_the_agents_are_combined():
    from src.agents import orchestrator
    a = {"issues": [], "total_cost_usd": 0.0, "warnings": ["static_analysis: piece failed"]}
    b = {"issues": [], "total_cost_usd": 0.0, "warnings": ["security: piece failed"]}
    with patch.object(orchestrator, "static_analysis_agent", AsyncMock(return_value=a)), \
         patch.object(orchestrator, "security_agent", AsyncMock(return_value=b)):
        merged = await _run_parallel_agents(state())
    assert merged["warnings"] == ["static_analysis: piece failed", "security: piece failed"]


@pytest.mark.asyncio
async def test_through_the_real_graph_a_crashed_agent_gives_an_incomplete_verdict():
    from src.agents import orchestrator
    clean = {"issues": [], "total_cost_usd": 0.0, "warnings": []}
    with patch.object(orchestrator, "static_analysis_agent", AsyncMock(return_value=clean)), \
         patch.object(orchestrator, "security_agent", AsyncMock(side_effect=RuntimeError("boom"))):
        final = await CodeReviewOrchestrator().review("j", "a.py", "x = 1\n")
    assert "LGTM" not in final["review_summary"]
    assert "INCOMPLETE REVIEW" in final["review_summary"]
    assert final["warnings"] == ["security: agent crashed; none of its findings are included"]


@pytest.mark.asyncio
async def test_through_the_real_graph_a_clean_review_is_still_lgtm():
    from src.agents import orchestrator
    clean = {"issues": [], "total_cost_usd": 0.0, "warnings": []}
    with patch.object(orchestrator, "static_analysis_agent", AsyncMock(return_value=clean)), \
         patch.object(orchestrator, "security_agent", AsyncMock(return_value=clean)):
        final = await CodeReviewOrchestrator().review("j", "a.py", "x = 1\n")
    assert "LGTM" in final["review_summary"] and final["warnings"] == []


# ---- API result -------------------------------------------------------------------

def test_the_api_result_says_when_a_review_is_incomplete():
    out = serialize_result({"job_id": "j", "issues": [], "fix_proposals": [], "warnings": ["w"]})
    assert out["complete"] is False and out["warnings"] == ["w"]


def test_the_api_result_is_complete_without_warnings():
    out = serialize_result({"job_id": "j", "issues": [], "fix_proposals": []})
    assert out["complete"] is True and out["warnings"] == []
