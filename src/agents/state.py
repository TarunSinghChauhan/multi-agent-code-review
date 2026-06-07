from typing import TypedDict, Annotated
from pydantic import BaseModel
import operator


# ─── Individual issue found by any agent ─────────────────────────────────────
class CodeIssue(BaseModel):
    agent: str
    issue_type: str
    severity: str  # critical | high | medium | low | info
    line_number: int | None = None
    title: str
    description: str
    suggestion: str | None = None


# ─── Fix proposed by the fix proposal agent ───────────────────────────────────
class FixProposal(BaseModel):
    issue_title: str
    original_code: str
    fixed_code: str
    explanation: str


# ─── LangGraph state — shared across all agents ───────────────────────────────
class PRState(TypedDict):
    # Input
    job_id: str
    filename: str
    language: str
    code: str

    # Agent outputs (use operator.add so each agent appends its issues)
    issues: Annotated[list[CodeIssue], operator.add]
    fix_proposals: Annotated[list[FixProposal], operator.add]

    # Cost tracking
    total_cost_usd: float

    # Final output
    review_summary: str
    severity_counts: dict[str, int]
    completed: bool
