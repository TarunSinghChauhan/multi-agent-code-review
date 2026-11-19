from typing import TypedDict, Annotated, NotRequired
from pydantic import BaseModel, field_validator
import operator


SEVERITIES = ("critical", "high", "medium", "low", "info")
_SEVERITY_ALIASES = {
    "severe": "critical",
    "moderate": "medium",
    "warning": "medium",
    "minor": "low",
    "informational": "info",
    "information": "info",
}


# Individual issue found by any agent
class CodeIssue(BaseModel):
    agent: str
    issue_type: str
    severity: str  # critical | high | medium | low | info
    line_number: int | None = None
    title: str
    description: str
    suggestion: str | None = None

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, value):
        """Model output is free text: "Critical", " HIGH " and "moderate" all show up.

        The merger counts and ranks by the five canonical names, so an unrecognised
        spelling used to be listed but never counted, and a "Critical" finding could not
        produce the do-not-merge verdict. Anything unknown becomes "medium".
        """
        if isinstance(value, str):
            key = value.strip().lower()
            if key in SEVERITIES:
                return key
            return _SEVERITY_ALIASES.get(key, "medium")
        return "medium"


# Fix proposed by the fix proposal agent
class FixProposal(BaseModel):
    issue_title: str
    original_code: str
    fixed_code: str
    explanation: str


# LangGraph state, shared across all agents
class PRState(TypedDict):
    # Input
    job_id: str
    filename: str
    language: str
    code: str

    # The parallel step returns one combined list and the merger returns the
    # deduplicated list. Plain replacement is correct here: using operator.add
    # would append the merger's list to the raw list and double-count.
    issues: list[CodeIssue]
    fix_proposals: Annotated[list[FixProposal], operator.add]

    # Cost tracking
    total_cost_usd: float

    # Final output
    review_summary: str
    severity_counts: dict[str, int]
    completed: bool

    # Things that could not be checked (an agent crashed, an LLM call failed). A review
    # with warnings is incomplete, so "no issues found" must not be read as "clean".
    warnings: NotRequired[list[str]]
