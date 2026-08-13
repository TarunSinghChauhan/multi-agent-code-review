from src.agents.state import CodeIssue
from src.agents.merger import merger_agent, _deduplicate, _severity_score


def make_issue(agent, issue_type, severity, line_number=1, title="Issue", description="desc"):
    return CodeIssue(
        agent=agent,
        issue_type=issue_type,
        severity=severity,
        line_number=line_number,
        title=title,
        description=description,
    )


def make_state(issues, fix_proposals=None):
    return {
        "job_id": "job_1",
        "filename": "app.py",
        "language": "python",
        "code": "",
        "issues": issues,
        "fix_proposals": fix_proposals or [],
        "total_cost_usd": 0.01,
        "review_summary": "",
        "severity_counts": {},
        "completed": False,
    }


def test_deduplicate_removes_exact_duplicates():
    issues = [
        make_issue("security", "eval_usage", "high", line_number=3),
        make_issue("security", "eval_usage", "high", line_number=3),
    ]
    result = _deduplicate(issues)
    assert len(result) == 1


def test_deduplicate_keeps_same_type_on_different_lines():
    issues = [
        make_issue("security", "eval_usage", "high", line_number=3),
        make_issue("security", "eval_usage", "high", line_number=10),
    ]
    result = _deduplicate(issues)
    assert len(result) == 2


def test_severity_score_ordering():
    assert _severity_score("critical") > _severity_score("high")
    assert _severity_score("high") > _severity_score("medium")
    assert _severity_score("medium") > _severity_score("low")
    assert _severity_score("low") > _severity_score("info")


def test_severity_score_unknown_defaults_to_zero():
    assert _severity_score("nonexistent") == 0


def test_merger_sorts_issues_by_severity_descending():
    issues = [
        make_issue("static_analysis", "style", "low"),
        make_issue("security", "hardcoded_password", "critical"),
        make_issue("security", "weak_hash", "medium"),
    ]
    state = make_state(issues)
    result = merger_agent(state)
    severities = [i.severity for i in result["issues"]]
    assert severities == ["critical", "medium", "low"]


def test_merger_verdict_critical_when_critical_issue_present():
    issues = [make_issue("security", "hardcoded_password", "critical")]
    state = make_state(issues)
    result = merger_agent(state)
    assert "CRITICAL" in result["review_summary"]
    assert "Do not merge" in result["review_summary"]


def test_merger_verdict_lgtm_when_no_issues():
    state = make_state([])
    result = merger_agent(state)
    assert "LGTM" in result["review_summary"]
    assert result["severity_counts"] == {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}


def test_merger_severity_counts_are_accurate():
    issues = [
        make_issue("security", "a", "critical"),
        make_issue("security", "b", "critical"),
        make_issue("static_analysis", "c", "medium"),
    ]
    state = make_state(issues)
    result = merger_agent(state)
    assert result["severity_counts"]["critical"] == 2
    assert result["severity_counts"]["medium"] == 1
    assert result["severity_counts"]["high"] == 0


def test_merger_marks_completed_true():
    state = make_state([])
    result = merger_agent(state)
    assert result["completed"] is True
