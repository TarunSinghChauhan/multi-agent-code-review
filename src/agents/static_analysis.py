import ast
import json
from openai import AsyncOpenAI

from src.agents.state import PRState, CodeIssue
from src.core.config import get_settings
from src.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)

client = AsyncOpenAI(
    api_key=settings.openrouter_api_key,
    base_url="https://openrouter.ai/api/v1",
)


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
    - Uses LLM for deeper code quality analysis
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

    # ── 2. LLM code quality analysis ─────────────────────────────────────────
    try:
        prompt = f"""Analyze this {state['language']} code for quality issues.

Code from file: {state['filename']}
```
{state['code'][:3000]}
```

Find issues with:
- Code complexity and readability
- Naming conventions
- Function/class design
- Missing docstrings
- Dead code or unused variables
- Performance concerns

Respond ONLY with valid JSON array:
[
  {{
    "issue_type": "string",
    "severity": "critical|high|medium|low|info",
    "line_number": null or integer,
    "title": "short title",
    "description": "clear description",
    "suggestion": "how to fix"
  }}
]

Return empty array [] if no issues found."""

        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert code reviewer. Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
            temperature=0.0,
            extra_headers={"HTTP-Referer": "https://github.com/multi-agent-code-review", "X-Title": "Code Review"},
        )

        raw = response.choices[0].message.content or "[]"
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()

        llm_issues = json.loads(raw)
        for issue in llm_issues:
            issues.append(CodeIssue(
                agent="static_analysis",
                issue_type=issue.get("issue_type", "code_quality"),
                severity=issue.get("severity", "medium"),
                line_number=issue.get("line_number"),
                title=issue.get("title", "Code Quality Issue"),
                description=issue.get("description", ""),
                suggestion=issue.get("suggestion"),
            ))

        if response.usage:
            cost = (response.usage.prompt_tokens * 0.15 + response.usage.completion_tokens * 0.60) / 1_000_000

    except Exception as e:
        logger.error("static_analysis_llm_failed", error=str(e))

    logger.info("static_analysis_agent_done", job_id=state["job_id"], issues_found=len(issues), cost=cost)
    return {"issues": issues, "total_cost_usd": state["total_cost_usd"] + cost}
