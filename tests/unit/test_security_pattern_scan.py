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
