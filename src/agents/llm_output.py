"""Turn a model's JSON issue list into CodeIssue objects without trusting its shape.

Before this, the agents built CodeIssue objects in one loop inside the same try block as
the API call, so a single malformed entry (a string instead of an object, a text line
number like "12-14") raised, dropped every later issue in that piece, and skipped the
cost accounting that came after the loop.
"""
from src.agents.chunking import shift_line
from src.agents.state import CodeIssue
from src.core.logging import get_logger

logger = get_logger(__name__)


def coerce_line(value):
    """Return an int line number, or None when the model gave something unusable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def parse_llm_issues(
    parsed,
    *,
    agent: str,
    default_type: str,
    default_severity: str,
    default_title: str,
    offset: int = 0,
) -> tuple[list[CodeIssue], int]:
    """Return (issues, skipped). Entries that cannot be read are counted, not fatal.

    parsed is the decoded JSON. A bare list is expected; {"issues": [...]} is accepted
    too, since models sometimes wrap the array. Line numbers are shifted by offset so they
    refer to the whole file when the model only saw one piece of it.
    """
    if isinstance(parsed, dict):
        parsed = parsed.get("issues")
    if not isinstance(parsed, list):
        return [], 1

    issues: list[CodeIssue] = []
    skipped = 0
    for item in parsed:
        if not isinstance(item, dict):
            skipped += 1
            continue
        try:
            suggestion = item.get("suggestion")
            issues.append(CodeIssue(
                agent=agent,
                issue_type=str(item.get("issue_type") or default_type),
                severity=item.get("severity") or default_severity,
                line_number=shift_line(coerce_line(item.get("line_number")), offset),
                title=str(item.get("title") or default_title),
                description=str(item.get("description") or ""),
                suggestion=str(suggestion) if suggestion else None,
            ))
        except Exception as e:  # a bad entry must not cost us the good ones
            logger.warning("llm_issue_skipped", agent=agent, error=str(e))
            skipped += 1
    return issues, skipped
