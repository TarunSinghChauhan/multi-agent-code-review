from src.agents.security import _pattern_scan


def test_detects_hardcoded_password():
    code = 'password = "supersecret123"'
    issues = _pattern_scan(code)
    types = [i.issue_type for i in issues]
    assert "hardcoded_password" in types


def test_detects_hardcoded_api_key():
    code = 'api_key = "sk-1234567890abcdef"'
    issues = _pattern_scan(code)
    types = [i.issue_type for i in issues]
    assert "hardcoded_api_key" in types


def test_detects_eval_usage():
    code = 'result = eval(user_input)'
    issues = _pattern_scan(code)
    types = [i.issue_type for i in issues]
    assert "eval_usage" in types


def test_detects_shell_injection_risk():
    code = 'subprocess.run(cmd, shell=True)'
    issues = _pattern_scan(code)
    types = [i.issue_type for i in issues]
    assert "shell_injection" in types


def test_detects_weak_hash_md5():
    code = 'digest = md5(data)'
    issues = _pattern_scan(code)
    types = [i.issue_type for i in issues]
    assert "weak_hash" in types


def test_line_number_is_correct():
    code = "x = 1\ny = 2\npassword = 'hunter2'\nz = 3"
    issues = _pattern_scan(code)
    password_issue = next(i for i in issues if i.issue_type == "hardcoded_password")
    assert password_issue.line_number == 3


def test_multiple_issues_on_same_line_are_all_caught():
    code = 'password = "x"; api_key = "y"'
    issues = _pattern_scan(code)
    types = [i.issue_type for i in issues]
    assert "hardcoded_password" in types
    assert "hardcoded_api_key" in types


def test_clean_code_has_no_issues():
    code = "def add(a, b):\n    return a + b\n"
    issues = _pattern_scan(code)
    assert issues == []


def test_case_insensitive_detection():
    code = 'DEBUG = True'
    issues = _pattern_scan(code)
    types = [i.issue_type for i in issues]
    assert "debug_mode" in types


def test_all_issues_are_tagged_with_security_agent():
    code = 'eval(x)\nexec(y)'
    issues = _pattern_scan(code)
    assert all(i.agent == "security" for i in issues)


import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.security import security_agent, _get_client


def make_state(code="x = 1\n", language="python"):
    return {
        "job_id": "job_1",
        "filename": "app.py",
        "language": language,
        "code": code,
        "total_cost_usd": 0.0,
    }


def test_get_client_constructs_and_caches_singleton():
    import src.agents.security as security_module
    security_module._client = None  # reset in case another test set it
    with patch("src.agents.security.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        client1 = _get_client()
        client2 = _get_client()
    assert client1 is client2  # singleton — second call returns the cached instance
    mock_cls.assert_called_once()  # constructor only invoked once, not on every call
    security_module._client = None  # reset for test isolation


@pytest.mark.asyncio
async def test_security_agent_includes_pattern_scan_issues():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="[]"))]
    fake_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("src.agents.security._get_client", return_value=fake_client):
        result = await security_agent(make_state(code='password = "hunter2"\n'))

    issue_types = [i.issue_type for i in result["issues"]]
    assert "hardcoded_password" in issue_types
    assert result["total_cost_usd"] > 0.0


@pytest.mark.asyncio
async def test_security_agent_merges_llm_issues():
    fake_client = MagicMock()
    llm_issues_json = '[{"issue_type": "auth_bypass", "severity": "critical", "title": "Auth bypass", "description": "Missing check", "suggestion": "add auth check"}]'
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content=llm_issues_json))]
    fake_response.usage = MagicMock(prompt_tokens=20, completion_tokens=10)
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("src.agents.security._get_client", return_value=fake_client):
        result = await security_agent(make_state(code="def safe():\n    return 1\n"))

    issue_types = [i.issue_type for i in result["issues"]]
    assert "auth_bypass" in issue_types


@pytest.mark.asyncio
async def test_security_agent_handles_missing_usage_gracefully():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="[]"))]
    fake_response.usage = None
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("src.agents.security._get_client", return_value=fake_client):
        result = await security_agent(make_state(code="def safe():\n    return 1\n"))

    assert result["total_cost_usd"] == 0.0


@pytest.mark.asyncio
async def test_security_agent_handles_llm_failure_gracefully():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("api down"))

    with patch("src.agents.security._get_client", return_value=fake_client):
        result = await security_agent(make_state(code="def safe():\n    return 1\n"))

    # Pattern-scan issues (none for this clean code) still return successfully despite LLM failure
    assert result["issues"] == []
    assert result["total_cost_usd"] == 0.0
