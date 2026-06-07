import uuid
import math
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from datetime import datetime

from src.agents.orchestrator import CodeReviewOrchestrator
from src.core.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)

_job_status: dict[str, str] = {}
_job_results: dict[str, dict] = {}


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
        "completed_at": datetime.utcnow().isoformat(),
        "total_issues": len(issues),
        "severity_counts": final_state.get("severity_counts", {}),
        "total_cost_usd": round(final_state.get("total_cost_usd", 0.0), 6),
        "review_summary": final_state.get("review_summary", ""),
        "issues": issues,
        "fix_proposals": proposals,
    }


class ReviewRequest(BaseModel):
    filename: str = "code.py"
    language: str = "python"
    code: str


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
        result = serialize_result(final_state)
        _job_results[job_id] = clean_nans(result)
        _job_status[job_id] = "completed"
    except Exception as e:
        import traceback
        logger.error("review_task_failed", job_id=job_id, error=str(e), traceback=traceback.format_exc())
        _job_status[job_id] = f"failed: {str(e)}"


@router.post("/submit")
async def submit_review(request: ReviewRequest, background_tasks: BackgroundTasks):
    """Submit code for multi-agent review."""
    job_id = str(uuid.uuid4())[:8]
    _job_status[job_id] = "pending"
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


@router.get("/jobs")
async def list_jobs():
    return {"jobs": [{"job_id": k, "status": v} for k, v in _job_status.items()]}


@router.post("/submit/sample")
async def submit_sample_review(background_tasks: BackgroundTasks):
    """Submit a built-in sample with intentional bugs for demo purposes."""
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
    _job_status[job_id] = "pending"
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