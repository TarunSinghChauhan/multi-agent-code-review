import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from src.api.main import app
from src.agents.state import PRState, CodeIssue
from src.agents.static_analysis import _analyze_python_ast
from src.agents.security import _pattern_scan
from src.agents.merger import merger_agent


# ─── Fixtures ─────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


SAMPLE_VULNERABLE_CODE = '''
import pickle
password = "admin123"
api_key = "sk-abc123"

def bad_function(data=[]):
    try:
        result = eval(data)
    except:
        pass

def hash_it(pwd):
    import hashlib
    return hashlib.md5(pwd.encode()).hexdigest()

def run_cmd(cmd):
    import subprocess
    return subprocess.run(cmd, shell=True)
'''

SAMPLE_CLEAN_CODE = '''
def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b

def greet(name: str) -> str:
    """Return a greeting."""
    return f"Hello, {name}!"
'''


# ─── Health ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/health/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


# ─── AST Analysis ─────────────────────────────────────────────────────────────
def test_ast_detects_bare_except():
    code = "try:\n    pass\nexcept:\n    pass"
    issues = _analyze_python_ast(code)
    assert any(i["type"] == "bare_except" for i in issues)


def test_ast_detects_mutable_default():
    code = "def f(x=[]):\n    return x"
    issues = _analyze_python_ast(code)
    assert any(i["type"] == "mutable_default_arg" for i in issues)


def test_ast_clean_code():
    code = "def add(a: int, b: int) -> int:\n    return a + b"
    issues = _analyze_python_ast(code)
    assert len(issues) == 0


def test_ast_syntax_error():
    code = "def f(:\n    pass"
    issues = _analyze_python_ast(code)
    assert any(i["type"] == "syntax_error" for i in issues)


# ─── Security Pattern Scan ────────────────────────────────────────────────────
def test_pattern_detects_hardcoded_password():
    issues = _pattern_scan('password = "admin123"')
    assert any(i.issue_type == "hardcoded_password" for i in issues)


def test_pattern_detects_eval():
    issues = _pattern_scan("result = eval(user_input)")
    assert any(i.issue_type == "eval_usage" for i in issues)


def test_pattern_detects_shell_true():
    issues = _pattern_scan("subprocess.run(cmd, shell=True)")
    assert any(i.issue_type == "shell_injection" for i in issues)


def test_pattern_detects_md5():
    issues = _pattern_scan("hashlib.md5(data)")
    assert any(i.issue_type == "weak_hash" for i in issues)


def test_pattern_detects_api_key():
    issues = _pattern_scan('api_key = "sk-abc123xyz"')
    assert any(i.issue_type == "hardcoded_api_key" for i in issues)


def test_pattern_clean_code():
    issues = _pattern_scan("def add(a, b):\n    return a + b")
    assert len(issues) == 0


# ─── Merger ───────────────────────────────────────────────────────────────────
def test_merger_deduplicates():
    state: PRState = {
        "job_id": "test",
        "filename": "test.py",
        "language": "python",
        "code": "",
        "issues": [
            CodeIssue(agent="security", issue_type="eval_usage", severity="high",
                     line_number=5, title="Eval", description="Dangerous"),
            CodeIssue(agent="security", issue_type="eval_usage", severity="high",
                     line_number=5, title="Eval", description="Dangerous"),  # duplicate
        ],
        "fix_proposals": [],
        "total_cost_usd": 0.01,
        "review_summary": "",
        "severity_counts": {},
        "completed": False,
    }
    result = merger_agent(state)
    assert len(result["issues"]) == 1


def test_merger_severity_counts():
    state: PRState = {
        "job_id": "test",
        "filename": "test.py",
        "language": "python",
        "code": "",
        "issues": [
            CodeIssue(agent="security", issue_type="a", severity="critical", title="A", description="A"),
            CodeIssue(agent="security", issue_type="b", severity="high", title="B", description="B"),
            CodeIssue(agent="static_analysis", issue_type="c", severity="medium", title="C", description="C"),
        ],
        "fix_proposals": [],
        "total_cost_usd": 0.0,
        "review_summary": "",
        "severity_counts": {},
        "completed": False,
    }
    result = merger_agent(state)
    assert result["severity_counts"]["critical"] == 1
    assert result["severity_counts"]["high"] == 1
    assert result["severity_counts"]["medium"] == 1


def test_merger_verdict_critical():
    state: PRState = {
        "job_id": "test",
        "filename": "test.py",
        "language": "python",
        "code": "",
        "issues": [
            CodeIssue(agent="security", issue_type="sql_injection", severity="critical",
                     title="SQL Injection", description="Dangerous query"),
        ],
        "fix_proposals": [],
        "total_cost_usd": 0.0,
        "review_summary": "",
        "severity_counts": {},
        "completed": False,
    }
    result = merger_agent(state)
    assert "CRITICAL" in result["review_summary"]


# ─── API endpoints ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_submit_returns_job_id(client):
    resp = await client.post("/reviews/submit", json={
        "filename": "test.py",
        "language": "python",
        "code": "def hello():\n    return 'world'",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_unknown_job_returns_404(client):
    resp = await client.get("/reviews/status/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_jobs(client):
    resp = await client.get("/reviews/jobs")
    assert resp.status_code == 200
    assert "jobs" in resp.json()
