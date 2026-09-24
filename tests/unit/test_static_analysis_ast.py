from src.agents.static_analysis import _analyze_python_ast


def test_detects_too_many_args():
    code = "def f(a, b, c, d, e, f, g, h):\n    pass\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "too_many_args" in types


def test_does_not_flag_reasonable_arg_count():
    code = "def f(a, b, c):\n    pass\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "too_many_args" not in types


def test_detects_bare_except():
    code = "try:\n    x = 1\nexcept:\n    pass\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "bare_except" in types


def test_does_not_flag_specific_except():
    code = "try:\n    x = 1\nexcept ValueError:\n    pass\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "bare_except" not in types


def test_detects_mutable_default_list():
    code = "def f(data=[]):\n    pass\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "mutable_default_arg" in types


def test_detects_mutable_default_dict():
    code = "def f(config={}):\n    pass\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "mutable_default_arg" in types


def test_does_not_flag_none_default():
    code = "def f(data=None):\n    pass\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "mutable_default_arg" not in types


def test_detects_global_variable_usage():
    code = "def f():\n    global x\n    x = 1\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "global_variable" in types


def test_detects_long_line():
    code = "x = " + "1" * 110 + "\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "long_line" in types


def test_syntax_error_returns_single_issue():
    code = "def f(:\n    pass\n"
    issues = _analyze_python_ast(code)
    assert len(issues) == 1
    assert issues[0]["type"] == "syntax_error"


def test_clean_code_has_no_issues():
    code = "def add(a, b):\n    return a + b\n"
    issues = _analyze_python_ast(code)
    assert issues == []


def test_detects_long_line_via_ast_col_offset():
    # An expression statement whose column offset itself exceeds 100 chars —
    # built via deep nesting so the source stays syntactically valid.
    depth = 30  # 30 * 4 = 120 columns of indentation
    lines = []
    for i in range(depth):
        lines.append("    " * i + "if True:")
    lines.append("    " * depth + "some_call()")
    code = "\n".join(lines) + "\n"
    issues = _analyze_python_ast(code)
    types = [i["type"] for i in issues]
    assert "long_line" in types


import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.static_analysis import static_analysis_agent


def make_state(code="def f(a, b, c, d, e, f, g, h):\n    pass\n", language="python"):
    return {
        "job_id": "job_1",
        "filename": "app.py",
        "language": language,
        "code": code,
        "total_cost_usd": 0.0,
    }


@pytest.mark.asyncio
async def test_static_analysis_agent_includes_ast_issues_for_python():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="[]"))]
    fake_response.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("src.agents.static_analysis._get_client", return_value=fake_client):
        result = await static_analysis_agent(make_state())

    issue_types = [i.issue_type for i in result["issues"]]
    assert "too_many_args" in issue_types
    assert result["total_cost_usd"] > 0.0


@pytest.mark.asyncio
async def test_static_analysis_agent_skips_ast_for_non_python():
    fake_client = MagicMock()
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content="[]"))]
    fake_response.usage = None
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("src.agents.static_analysis._get_client", return_value=fake_client):
        result = await static_analysis_agent(make_state(code="function f() {}", language="javascript"))

    assert result["issues"] == []


@pytest.mark.asyncio
async def test_static_analysis_agent_merges_llm_issues():
    fake_client = MagicMock()
    llm_issues_json = '[{"issue_type": "naming", "severity": "low", "title": "Bad name", "description": "x is unclear", "suggestion": "rename it"}]'
    fake_response = MagicMock()
    fake_response.choices = [MagicMock(message=MagicMock(content=llm_issues_json))]
    fake_response.usage = MagicMock(prompt_tokens=20, completion_tokens=10)
    fake_client.chat.completions.create = AsyncMock(return_value=fake_response)

    with patch("src.agents.static_analysis._get_client", return_value=fake_client):
        result = await static_analysis_agent(make_state(code="def add(a, b):\n    return a + b\n"))

    issue_types = [i.issue_type for i in result["issues"]]
    assert "naming" in issue_types


@pytest.mark.asyncio
async def test_static_analysis_agent_handles_llm_failure_gracefully():
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=RuntimeError("api down"))

    with patch("src.agents.static_analysis._get_client", return_value=fake_client):
        result = await static_analysis_agent(make_state(code="def add(a, b):\n    return a + b\n"))

    # AST issues (none for this clean code) still return successfully despite LLM failure
    assert result["issues"] == []
    assert result["total_cost_usd"] == 0.0


def test_get_client_constructs_and_caches_singleton():
    import src.agents.static_analysis as static_analysis_module
    from src.agents.static_analysis import _get_client
    static_analysis_module._client = None  # reset in case another test set it
    with patch("src.agents.static_analysis.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        client1 = _get_client()
        client2 = _get_client()
    assert client1 is client2  # singleton — second call returns the cached instance
    mock_cls.assert_called_once()  # constructor only invoked once, not on every call
    static_analysis_module._client = None  # reset for test isolation
