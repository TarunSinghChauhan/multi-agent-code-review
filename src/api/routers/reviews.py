import os
import time
import uuid
import math
from collections import defaultdict, deque
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.agents.orchestrator import CodeReviewOrchestrator
from src.core.database import AsyncSessionLocal, ReviewJob
from src.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

# Public-demo guardrails (override with environment variables)
MAX_CODE_CHARS = int(os.getenv("MAX_CODE_CHARS", "6000"))
DAILY_REVIEW_LIMIT = int(os.getenv("DAILY_REVIEW_LIMIT", "30"))
PER_IP_HOURLY_LIMIT = int(os.getenv("PER_IP_HOURLY_LIMIT", "5"))
MAX_STORED_JOBS = 100

_job_status: dict[str, str] = {}
_job_results: dict[str, dict] = {}
_ip_hits: dict[str, deque] = defaultdict(deque)
_daily = {"day": "", "count": 0}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _client_ip(http_request: Request) -> str:
    forwarded = http_request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return http_request.client.host if http_request.client else "unknown"


def _enforce_limits(http_request: Request) -> None:
    """Best-effort limits. The OpenRouter key's credit limit is the hard backstop."""
    now = time.time()
    today = _today()
    if _daily["day"] != today:
        _daily["day"], _daily["count"] = today, 0
    if _daily["count"] >= DAILY_REVIEW_LIMIT:
        raise HTTPException(status_code=429, detail="Daily demo limit reached. Please try again tomorrow.")

    if len(_ip_hits) > 5000:
        _ip_hits.clear()
    hits = _ip_hits[_client_ip(http_request)]
    while hits and now - hits[0] > 3600:
        hits.popleft()
    if len(hits) >= PER_IP_HOURLY_LIMIT:
        raise HTTPException(status_code=429, detail="Hourly limit reached for your connection. Please try again later.")

    hits.append(now)
    _daily["count"] += 1


def _remember(job_id: str) -> None:
    """Keep only the most recent jobs in memory."""
    _job_status[job_id] = "pending"
    while len(_job_status) > MAX_STORED_JOBS:
        oldest = next(iter(_job_status))
        _job_status.pop(oldest, None)
        _job_results.pop(oldest, None)


def clean_nans(obj):
    if isinstance(obj, float):
        return 0.0 if (math.isnan(obj) or math.isinf(obj)) else obj
    elif isinstance(obj, dict):
        return {k: clean_nans(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nans(v) for v in obj]
    return obj


def serialize_result(final_state: dict) -> dict:
    """Convert LangGraph state to JSON-serializable dict."""
    issues = []
    for issue in final_state.get("issues", []):
        if hasattr(issue, 'model_dump'):
            issues.append(issue.model_dump())
        elif isinstance(issue, dict):
            issues.append(issue)

    proposals = []
    for prop in final_state.get("fix_proposals", []):
        if hasattr(prop, 'model_dump'):
            proposals.append(prop.model_dump())
        elif isinstance(prop, dict):
            proposals.append(prop)

    return {
        "job_id": final_state.get("job_id"),
        "filename": final_state.get("filename"),
        "language": final_state.get("language"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "total_issues": len(issues),
        "severity_counts": final_state.get("severity_counts", {}),
        "total_cost_usd": round(final_state.get("total_cost_usd", 0.0), 6),
        "review_summary": final_state.get("review_summary", ""),
        "issues": issues,
        "fix_proposals": proposals,
    }


class ReviewRequest(BaseModel):
    filename: str = Field(default="code.py", max_length=100)
    language: str = Field(default="python", pattern="^python$")
    code: str = Field(min_length=1, max_length=MAX_CODE_CHARS)


async def _save_job(job_id: str, request: ReviewRequest, result: dict) -> None:
    """Best-effort: store review metadata in Postgres."""
    try:
        async with AsyncSessionLocal() as session:
            session.add(ReviewJob(
                id=job_id,
                filename=request.filename,
                language=request.language,
                status="completed",
                completed_at=datetime.now(timezone.utc).replace(tzinfo=None),
                total_cost_usd=result.get("total_cost_usd", 0.0),
                total_issues=result.get("total_issues", 0),
                critical_issues=(result.get("severity_counts") or {}).get("critical", 0),
            ))
            await session.commit()
    except Exception as exc:
        logger.warning("job_save_failed", job_id=job_id, error=str(exc))


async def _run_review_task(job_id: str, request: ReviewRequest):
    orchestrator = CodeReviewOrchestrator()
    try:
        _job_status[job_id] = "running"
        final_state = await orchestrator.review(
            job_id=job_id,
            filename=request.filename,
            code=request.code,
            language=request.language,
        )
        result = clean_nans(serialize_result(final_state))
        _job_results[job_id] = result
        _job_status[job_id] = "completed"
        await _save_job(job_id, request, result)
    except Exception as e:
        import traceback
        logger.error("review_task_failed", job_id=job_id, error=str(e), traceback=traceback.format_exc())
        _job_status[job_id] = "failed: the review could not be completed"


@router.get("/limits")
async def limits():
    used = _daily["count"] if _daily["day"] == _today() else 0
    return {
        "daily_limit": DAILY_REVIEW_LIMIT,
        "used_today": used,
        "remaining_today": max(0, DAILY_REVIEW_LIMIT - used),
        "max_code_chars": MAX_CODE_CHARS,
    }


@router.post("/submit")
async def submit_review(request: ReviewRequest, http_request: Request, background_tasks: BackgroundTasks):
    """Submit code for multi-agent review."""
    _enforce_limits(http_request)
    job_id = str(uuid.uuid4())[:8]
    _remember(job_id)
    background_tasks.add_task(_run_review_task, job_id, request)
    return {
        "job_id": job_id,
        "status": "pending",
        "message": f"Review started. Poll /reviews/status/{job_id} for updates.",
    }


@router.get("/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in _job_status:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"job_id": job_id, "status": _job_status[job_id]}


@router.get("/results/{job_id}")
async def get_results(job_id: str):
    if job_id not in _job_status:
        raise HTTPException(status_code=404, detail="Job not found")
    if _job_status[job_id] != "completed":
        raise HTTPException(status_code=202, detail=f"Job status: {_job_status[job_id]}")
    return JSONResponse(content=_job_results[job_id])


@router.post("/submit/sample")
async def submit_sample_review(http_request: Request, background_tasks: BackgroundTasks):
    """Submit a built-in sample with intentional bugs for demo purposes."""
    _enforce_limits(http_request)
    sample_code = '''import pickle
import hashlib
import subprocess
import random

# Hardcoded credentials - never do this
password = "admin123"
api_key = "sk-prod-abc123xyz"

def get_user(user_id):
    query = "SELECT * FROM users WHERE id = %s" % user_id
    return query

def hash_password(pwd):
    return hashlib.md5(pwd.encode()).hexdigest()

def run_command(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True)
    return result.stdout

def process_data(data=[], config={}):
    try:
        result = eval(data)
        return result
    except:
        pass

def generate_token():
    return random.randint(100000, 999999)

def load_user_data(filepath):
    with open(filepath, "rb") as f:
        return pickle.load(f)

DEBUG = True
'''

    job_id = str(uuid.uuid4())[:8]
    _remember(job_id)
    request = ReviewRequest(
        filename="vulnerable_code.py",
        language="python",
        code=sample_code,
    )
    background_tasks.add_task(_run_review_task, job_id, request)
    return {
        "job_id": job_id,
        "status": "pending",
        "message": f"Sample review started. Poll /reviews/status/{job_id}",
    }
