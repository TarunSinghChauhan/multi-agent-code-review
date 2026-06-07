import asyncio
from langgraph.graph import StateGraph, END

from src.agents.state import PRState
from src.agents.static_analysis import static_analysis_agent
from src.agents.security import security_agent
from src.agents.fix_proposal import fix_proposal_agent
from src.agents.merger import merger_agent
from src.core.config import get_settings
from src.core.logging import get_logger

settings = get_settings()
logger = get_logger(__name__)


def _check_cost_budget(state: PRState) -> str:
    """Route to fix proposals or skip based on cost budget."""
    if state["total_cost_usd"] >= settings.max_cost_per_review_usd:
        logger.warning("cost_budget_exceeded", cost=state["total_cost_usd"])
        return "merge"
    return "fix"


async def _run_parallel_agents(state: PRState) -> dict:
    """Run static analysis and security agents in parallel."""
    logger.info("parallel_agents_started", job_id=state["job_id"])
    results = await asyncio.gather(
        static_analysis_agent(state),
        security_agent(state),
        return_exceptions=True,
    )

    merged = {"issues": [], "total_cost_usd": state["total_cost_usd"]}
    for result in results:
        if isinstance(result, Exception):
            logger.error("agent_failed", error=str(result))
            continue
        merged["issues"].extend(result.get("issues", []))
        merged["total_cost_usd"] += result.get("total_cost_usd", 0) - state["total_cost_usd"]

    return merged


def build_review_graph() -> StateGraph:
    """
    Build the LangGraph multi-agent review pipeline.

    Flow:
    START → parallel_agents (static + security) → cost_check → fix_proposal → merger → END
    """
    graph = StateGraph(PRState)

    # Add nodes
    graph.add_node("parallel_agents", _run_parallel_agents)
    graph.add_node("fix_proposal", fix_proposal_agent)
    graph.add_node("merger", merger_agent)

    # Add edges
    graph.set_entry_point("parallel_agents")

    # Conditional routing based on cost budget
    graph.add_conditional_edges(
        "parallel_agents",
        _check_cost_budget,
        {
            "fix": "fix_proposal",
            "merge": "merger",
        }
    )

    graph.add_edge("fix_proposal", "merger")
    graph.add_edge("merger", END)

    return graph.compile()


class CodeReviewOrchestrator:
    """Orchestrates the full multi-agent code review pipeline."""

    def __init__(self):
        self.graph = build_review_graph()

    async def review(
        self,
        job_id: str,
        filename: str,
        code: str,
        language: str = "python",
    ) -> dict:
        """Run a complete code review and return structured results."""
        logger.info("review_started", job_id=job_id, filename=filename)

        initial_state: PRState = {
            "job_id": job_id,
            "filename": filename,
            "language": language,
            "code": code,
            "issues": [],
            "fix_proposals": [],
            "total_cost_usd": 0.0,
            "review_summary": "",
            "severity_counts": {},
            "completed": False,
        }

        try:
            final_state = await self.graph.ainvoke(initial_state)
            logger.info(
                "review_completed",
                job_id=job_id,
                total_issues=len(final_state["issues"]),
                cost=final_state["total_cost_usd"],
            )
            return final_state
        except Exception as e:
            logger.error("review_failed", job_id=job_id, error=str(e))
            raise
