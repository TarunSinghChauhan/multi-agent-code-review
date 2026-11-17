"""Model output is free text: spellings, shapes and line numbers vary, and none of it may crash a review."""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agents.llm_output import coerce_line, parse_llm_issues
from src.agents.merger import _deduplicate, merger_agent
from src.agents.security import calculate_llm_cost, security_agent
from src.agents.state import CodeIssue
from src.agents.static_analysis import static_analysis_agent


def issue(severity="high", **kw):
    base = dict(agent="security", issue_type="sqli", severity=severity, line_number=1,
                title="t", description="d")
    base.update(kw)
    return CodeIssue(**base)


# ---- severity normalisation ----------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("critical", "critical"), ("Critical", "critical"), ("CRITICAL", "critical"),
    ("  High ", "high"), ("Medium", "medium"), ("LOW", "low"), ("Info", "info"),
    ("moderate", "medium"), ("Warning", "medium"), ("minor", "low"),
    ("Informational", "info"), ("severe", "critical"),
    ("banana", "medium"), ("", "medium"), (None, "medium"), (3, "medium"),
])
def test_severity_is_normalised(raw, expected):
    assert issue(severity=raw).severity == expected


def make_state(issues):
    return {
        "job_id": "j", "filename": "app.py", "language": "python", "code": "",
        "issues": issues, "fix_proposals": [], "total_cost_usd": 0.0,
        "review_summary": "", "severity_counts": {}, "completed": False,
    }


def test_a_model_that_writes_Critical_still_produces_the_do_not_merge_verdict():
    result = merger_agent(make_state([issue(severity="Critical")]))
    assert result["severity_counts"]["critical"] == 1
    assert "Do not merge" in result["review_summary"]


def test_every_issue_is_counted_in_some_severity_bucket():
    issues = [issue(severity=s, line_number=i) for i, s in enumerate(["High", "moderate", "weird", "LOW"])]
    counts = merger_agent(make_state(issues))["severity_counts"]
    assert sum(counts.values()) == 4


# ---- line numbers --------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (5, 5), ("12", 12), (" 7 ", 7), (9.0, 9), (None, None), (True, None),
    ("12-14", None), ("line 3", None), (2.5, None), ([], None),
])
def test_coerce_line(value, expected):
    assert coerce_line(value) == expected


def test_numeric_string_line_numbers_are_shifted_like_integers():
    issues, skipped = parse_llm_issues(
        [{"title": "x", "line_number": "5"}], agent="a", default_type="t",
        default_severity="low", default_title="d", offset=100,
    )
    assert skipped == 0 and issues[0].line_number == 105


# ---- tolerant parsing ----------------------------------------------------------

def parse(items, **kw):
    return parse_llm_issues(items, agent="a", default_type="t", default_severity="low",
                            default_title="d", **kw)


def test_malformed_entries_are_skipped_and_the_rest_kept():
    issues, skipped = parse([
        {"title": "first", "line_number": 1},
        "this is not an object",
        {"title": "range", "line_number": "12-14"},   # unusable line -> kept without one
        None,
        {"title": "last", "line_number": 9},
    ])
    assert [i.title for i in issues] == ["first", "range", "last"]
    assert issues[1].line_number is None
    assert skipped == 2


def test_missing_and_null_fields_fall_back_to_the_defaults():
    issues, _ = parse([{"title": None, "issue_type": None, "severity": None, "description": None}])
    assert (issues[0].title, issues[0].issue_type, issues[0].severity, issues[0].description) == ("d", "t", "low", "")


def test_a_wrapped_list_is_accepted():
    issues, skipped = parse({"issues": [{"title": "a"}, {"title": "b"}]})
    assert [i.title for i in issues] == ["a", "b"] and skipped == 0


@pytest.mark.parametrize("junk", ["text", 5, None, {"other": 1}, {"issues": "nope"}])
def test_a_reply_of_the_wrong_shape_yields_nothing_instead_of_raising(junk):
    assert parse(junk) == ([], 1)


# ---- agents: one bad entry does not cost the rest of the piece, or its cost -------

def reply(content, prompt_tokens=1000, completion_tokens=500):
    r = MagicMock()
    r.choices = [MagicMock(message=MagicMock(content=content))]
    r.usage = MagicMock(prompt_tokens=prompt_tokens, completion_tokens=completion_tokens)
    return r


CASES = [
    ("src.agents.security._get_client", security_agent),
    ("src.agents.static_analysis._get_client", static_analysis_agent),
]
BAD_REPLY = json.dumps([
    {"issue_type": "x", "severity": "Critical", "line_number": 3, "title": "first"},
    "garbage entry",
    {"issue_type": "x", "severity": "low", "line_number": "7", "title": "after the garbage"},
])


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_findings_after_a_malformed_entry_are_kept_and_cost_is_counted(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply(BAD_REPLY))
    state = {"job_id": "j", "filename": "a.py", "language": "python", "code": "x = 1\n",
             "total_cost_usd": 0.0}
    with patch(target, return_value=client):
        result = await agent(state)
    llm = [i for i in result["issues"] if i.issue_type == "x"]
    assert [i.title for i in llm] == ["first", "after the garbage"]
    assert llm[0].severity == "critical" and llm[1].line_number == 7
    assert result["total_cost_usd"] == pytest.approx(calculate_llm_cost(1000, 500))


@pytest.mark.asyncio
@pytest.mark.parametrize("target,agent", CASES)
async def test_tokens_spent_on_an_unparseable_reply_are_still_costed(target, agent):
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=reply("not json at all"))
    state = {"job_id": "j", "filename": "a.py", "language": "python", "code": "x = 1\n",
             "total_cost_usd": 0.0}
    with patch(target, return_value=client):
        result = await agent(state)
    assert result["total_cost_usd"] == pytest.approx(calculate_llm_cost(1000, 500))


# ---- merger: findings without a line number --------------------------------------

def test_two_different_findings_without_line_numbers_are_both_kept():
    a = issue(line_number=None, title="SQL injection in login")
    b = issue(line_number=None, title="SQL injection in search")
    assert len(_deduplicate([a, b])) == 2


def test_the_same_finding_without_a_line_number_is_still_deduplicated():
    a = issue(line_number=None, title="SQL injection in login")
    assert len(_deduplicate([a, a.model_copy()])) == 1
