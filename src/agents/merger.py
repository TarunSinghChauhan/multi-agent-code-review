from src.agents.state import PRState, CodeIssue
from src.core.logging import get_logger

logger = get_logger(__name__)


def _deduplicate(issues: list[CodeIssue]) -> list[CodeIssue]:
    """Remove duplicate issues based on type + line number."""
    seen = set()
    unique = []
    for issue in issues:
        key = (issue.issue_type, issue.line_number, issue.agent)
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def _severity_score(severity: str) -> int:
    return {"critical": 4, "high": 3, "medium": 2, "low": 1, "info": 0}.get(severity, 0)


def merger_agent(state: PRState) -> dict:
    """
    Final agent: Result Merger
    - Deduplicates issues from all agents
    - Ranks by severity
    - Builds final summary
    - Computes severity counts
    """
    logger.info("merger_agent_started", job_id=state["job_id"])

    # Deduplicate and sort by severity
    unique_issues = _deduplicate(state["issues"])
    sorted_issues = sorted(unique_issues, key=lambda x: _severity_score(x.severity), reverse=True)

    # Count by severity
    severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for issue in sorted_issues:
        if issue.severity in severity_counts:
            severity_counts[issue.severity] += 1

    # Build summary
    total = len(sorted_issues)
    critical = severity_counts["critical"]
    high = severity_counts["high"]

    if critical > 0:
        verdict = "🔴 CRITICAL ISSUES FOUND — Do not merge"
    elif high > 0:
        verdict = "🟡 HIGH SEVERITY ISSUES — Review required before merge"
    elif total > 0:
        verdict = "🟢 MINOR ISSUES — Consider fixing before merge"
    else:
        verdict = "✅ LGTM — No significant issues found"

    summary_lines = [
        f"## Code Review Summary — {state['filename']}",
        f"**Verdict:** {verdict}",
        f"**Total Issues:** {total} ({critical} critical, {high} high, {severity_counts['medium']} medium, {severity_counts['low']} low)",
        f"**Total Cost:** ${state['total_cost_usd']:.4f}",
        "",
        "### Issues by Agent",
    ]

    agents = ["static_analysis", "security", "fix_proposal"]
    for agent in agents:
        agent_issues = [i for i in sorted_issues if i.agent == agent]
        if agent_issues:
            summary_lines.append(f"\n**{agent.replace('_', ' ').title()}** ({len(agent_issues)} issues)")
            for issue in agent_issues[:5]:  # Show top 5 per agent
                line_ref = f" (line {issue.line_number})" if issue.line_number else ""
                summary_lines.append(f"- [{issue.severity.upper()}]{line_ref} {issue.title}: {issue.description}")

    if state["fix_proposals"]:
        summary_lines.append(f"\n### Fix Proposals ({len(state['fix_proposals'])} generated)")
        for fix in state["fix_proposals"]:
            summary_lines.append(f"- **{fix.issue_title}**: {fix.explanation}")

    review_summary = "\n".join(summary_lines)

    logger.info(
        "merger_agent_done",
        job_id=state["job_id"],
        total_issues=total,
        critical=critical,
        cost=state["total_cost_usd"],
    )

    return {
        "issues": sorted_issues,
        "review_summary": review_summary,
        "severity_counts": severity_counts,
        "completed": True,
    }
