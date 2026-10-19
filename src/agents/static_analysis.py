import ast
import json
from openai import AsyncOpenAI

from src.agents.state import PRState, CodeIssue
from src.core.config import get_settings
from src.core.logging import get_logger
from src.agents.security import calculate_llm_cost, strip_json_fence

settings = get_settings()
logger = get_logger(__name__)

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    """Lazily construct the OpenAI client on first use, not at import time
    (see src/agents/security.py for the same pattern and rationale)."""
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


def _analyze_python_ast(code: str) -> list[dict]:
    """Pure static analysis using Python's AST — no API calls needed."""
    issues = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [{"type": "syntax_error", "line": e.lineno, "msg": str(e)}]

    for node in ast.walk(tree):
        # Functions with too many arguments
        if isinstance(node, ast.FunctionDef):
            if len(node.args.args) > 7:
                issues.append({
                    "type": "too_many_args",
                    "line": node.lineno,
                    "msg": f"Function '{node.name}' has {len(node.args.args)} arguments (max recommended: 7)",
                })

        # Bare except clauses
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            issues.append({
                "type": "bare_except",
                "line": node.lineno,
                "msg": "Bare 'except:' clause catches all exceptions including KeyboardInterrupt",
            })

        # Mutable default arguments
        if isinstance(node, ast.FunctionDef):
            for default in node.args.defaults:
                if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                    issues.append({
                        "type": "mutable_default_arg",
                        "line": node.lineno,
                        "msg": f"Function '{node.name}' uses mutable default argument",
                    })

        # Global variables
        if isinstance(node, ast.Global):
            issues.append({
                "type": "global_variable",
                "line": node.lineno,
                "msg": f"Use of global variables: {', '.join(node.names)}",
            })

        # Long lines via AST col_offset approximation
        if isinstance(node, ast.Expr) and hasattr(node, 'col_offset'):
            if node.col_offset > 100:
                issues.append({
                    "type": "long_line",
                    "line": node.lineno,
                    "msg": "Line may exceed 100 characters",
                })

    # Check line length directly
    for i, line in enumerate(code.split('\n'), 1):
        if len(line) > 100:
            issues.append({
                "type": "long_line",
                "line": i,
                "msg": f"Line {i} is {len(line)} characters (max: 100)",
            })

    return issues


async def static_analysis_agent(state: PRState) -> dict:
    """
    Agent 1: Static Analysis
    - Runs AST-based checks (no API cost)
    - Uses LLM for deeper code quality analysis (when LLM_ENABLED=true)
    - Checks complexity, naming, structure
    """
    logger.info("static_analysis_agent_started", job_id=state["job_id"])
    issues: list[CodeIssue] = []
    cost = 0.0

    # ── 1. AST analysis (free) ────────────────────────────────────────────────
    if state["language"] == "python":
        ast_issues = _analyze_python_ast(state["code"])
        for issue in ast_issues:
            issues.append(CodeIssue(
                agent="static_analysis",
                issue_type=issue["type"],
                severity="medium",
                line_number=issue.get("line"),
                title=issue["type"].replace("_", " ").title(),
                description=issue["msg"],
                suggestion="Refactor to follow Python best practices",
            ))

    # ── 2. LLM code quality analysis (skipped when LLM_ENABLED=false) ────────
    if not settings.llm_enabled:
        logger.info("static_llm_skipped", job_id=state["job_id"])
        return {"issues": issues, "total_cost_usd": state["total_cost_usd"]}

    try:
        prompt = f"""Analyze this {state['language']} code for quality issues.

Code from file: {state['filename']}
