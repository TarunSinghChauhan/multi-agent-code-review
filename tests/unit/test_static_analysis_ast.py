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
