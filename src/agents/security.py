import re
import json
from openai import AsyncOpenAI

from src.agents.state import PRState, CodeIssue
from src.core.config import get_settings
from src.core.logging import get_logger


def calculate_llm_cost(prompt_tokens: int, completion_tokens: int) -> float:
    """Cost in USD for gpt-4o-mini pricing: $0.15/1M input, $0.60/1M output tokens."""
    return (prompt_tokens * 0.15 + completion_tokens * 0.60) / 1_000_000


def strip_json_fence(raw: str) -> str:
    """Strip a markdown code fence (```json or plain ```) from an LLM response, if present."""
    if "```json" in raw:
        return raw.split("```json")[1].split("```")[0].strip()
    elif "```" in raw:
        return raw.split("```")[1].split("```")[0].strip()
    return raw

settings = get_settings()
logger = get_logger(__name__)

client = AsyncOpenAI(
    api_key=settings.openrouter_api_key,
    base_url="https://openrouter.ai/api/v1",
)

# ─── Pattern-based security checks (free, no API) ─────────────────────────────
SECURITY_PATTERNS = [
    {
        "pattern": r"password\s*=\s*['\"][^'\"]+['\"]",
        "type": "hardcoded_password",
        "severity": "critical",
        "title": "Hardcoded Password",
        "description": "Password is hardcoded in source code",
        "suggestion": "Use environment variables or a secrets manager",
    },
    {
        "pattern": r"(api_key|apikey|api_secret)\s*=\s*['\"][^'\"]+['\"]",
        "type": "hardcoded_api_key",
        "severity": "critical",
        "title": "Hardcoded API Key",
        "description": "API key is hardcoded in source code",
        "suggestion": "Store secrets in environment variables, never in code",
    },
    {
        "pattern": r"eval\s*\(",
        "type": "eval_usage",
        "severity": "high",
        "title": "Dangerous eval() Usage",
        "description": "eval() can execute arbitrary code and is a security risk",
        "suggestion": "Use safer alternatives like ast.literal_eval() for data parsing",
    },
    {
        "pattern": r"exec\s*\(",
        "type": "exec_usage",
        "severity": "high",
        "title": "Dangerous exec() Usage",
        "description": "exec() can execute arbitrary code",
        "suggestion": "Avoid exec() — restructure code to avoid dynamic execution",
    },
    {
        "pattern": r"shell\s*=\s*True",
        "type": "shell_injection",
        "severity": "high",
        "title": "Shell Injection Risk",
        "description": "shell=True in subprocess calls can lead to shell injection",
        "suggestion": "Use shell=False and pass arguments as a list",
    },
    {
        "pattern": r"pickle\.loads?\s*\(",
        "type": "insecure_deserialization",
        "severity": "high",
        "title": "Insecure Deserialization",
        "description": "pickle.load() can execute arbitrary code when loading untrusted data",
        "suggestion": "Use JSON or other safe serialization formats",
    },
    {
        "pattern": r"md5\s*\(",
        "type": "weak_hash",
        "severity": "medium",
        "title": "Weak Hash Algorithm (MD5)",
        "description": "MD5 is cryptographically broken",
        "suggestion": "Use SHA-256 or bcrypt for security-sensitive hashing",
    },
    {
        "pattern": r"sha1\s*\(",
        "type": "weak_hash",
        "severity": "medium",
        "title": "Weak Hash Algorithm (SHA1)",
        "description": "SHA1 is no longer considered secure",
        "suggestion": "Use SHA-256 or stronger",
    },
    {
        "pattern": r"random\.(random|randint|choice)\s*\(",
        "type": "insecure_random",
        "severity": "medium",
        "title": "Insecure Random Number Generator",
        "description": "random module is not cryptographically secure",
        "suggestion": "Use secrets module for security-sensitive randomness",
    },
    {
        "pattern": r"verify\s*=\s*False",
        "type": "ssl_verification_disabled",
        "severity": "high",
        "title": "SSL Verification Disabled",
        "description": "Disabling SSL verification exposes the app to MITM attacks",
        "suggestion": "Always keep SSL verification enabled in production",
    },
    {
        "pattern": r"DEBUG\s*=\s*True",
        "type": "debug_mode",
        "severity": "medium",
        "title": "Debug Mode Enabled",
        "description": "Debug mode should never be enabled in production",
        "suggestion": "Use environment variables to control debug mode",
    },
    {
        "pattern": r"SELECT\s+\*\s+FROM.*%s|SELECT\s+\*\s+FROM.*format\(",
        "type": "sql_injection",
        "severity": "critical",
        "title": "Potential SQL Injection",
        "description": "String formatting in SQL queries can lead to SQL injection",
        "suggestion": "Use parameterized queries or an ORM",
    },
]


def _pattern_scan(code: str) -> list[CodeIssue]:
    """Scan code with regex patterns — fast, no API cost."""
    issues = []
    lines = code.split('\n')
    for i, line in enumerate(lines, 1):
        for check in SECURITY_PATTERNS:
            if re.search(check["pattern"], line, re.IGNORECASE):
                issues.append(CodeIssue(
                    agent="security",
                    issue_type=check["type"],
                    severity=check["severity"],
                    line_number=i,
                    title=check["title"],
                    description=check["description"],
                    suggestion=check["suggestion"],
                ))
    return issues


async def security_agent(state: PRState) -> dict:
    """
    Agent 2: Security Scanner
    - Pattern-based scan (OWASP Top 10 patterns)
    - LLM deep security analysis
    - Identifies hardcoded secrets, injection risks, insecure patterns
    """
    logger.info("security_agent_started", job_id=state["job_id"])
    issues: list[CodeIssue] = []
    cost = 0.0

    # ── 1. Pattern scan (free) ────────────────────────────────────────────────
    pattern_issues = _pattern_scan(state["code"])
    issues.extend(pattern_issues)

    # ── 2. LLM deep security analysis ─────────────────────────────────────────
    try:
        prompt = f"""Perform a security audit of this {state['language']} code.

File: {state['filename']}
```
{state['code'][:3000]}
```

Check for:
- Injection vulnerabilities (SQL, command, LDAP)
- Authentication and authorization flaws
- Sensitive data exposure
- Security misconfiguration
- Insecure direct object references
- Cross-site scripting (if applicable)
- Insecure dependencies usage
- Input validation issues

Respond ONLY with valid JSON array:
[
  {{
    "issue_type": "string",
    "severity": "critical|high|medium|low|info",
    "line_number": null or integer,
    "title": "short title",
    "description": "clear description of the vulnerability",
    "suggestion": "how to fix securely"
  }}
]

Return [] if no additional security issues found beyond obvious ones."""

        response = await client.chat.completions.create(
            model="openai/gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an expert security engineer specializing in code security audits. Respond only with valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
            temperature=0.0,
            extra_headers={"HTTP-Referer": "https://github.com/multi-agent-code-review", "X-Title": "Code Review"},
        )

        raw = response.choices[0].message.content or "[]"
        raw = strip_json_fence(raw)

        llm_issues = json.loads(raw)
        for issue in llm_issues:
            issues.append(CodeIssue(
                agent="security",
                issue_type=issue.get("issue_type", "security"),
                severity=issue.get("severity", "high"),
                line_number=issue.get("line_number"),
                title=issue.get("title", "Security Issue"),
                description=issue.get("description", ""),
                suggestion=issue.get("suggestion"),
            ))

        if response.usage:
            cost = calculate_llm_cost(response.usage.prompt_tokens, response.usage.completion_tokens)

    except Exception as e:
        logger.error("security_agent_llm_failed", error=str(e))

    logger.info("security_agent_done", job_id=state["job_id"], issues_found=len(issues), cost=cost)
    return {"issues": issues, "total_cost_usd": state["total_cost_usd"] + cost}
