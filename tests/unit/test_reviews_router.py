import math
from types import SimpleNamespace

from src.api.routers.reviews import clean_nans, serialize_result


def test_clean_nans_replaces_nan():
    assert clean_nans(float("nan")) == 0.0


def test_clean_nans_leaves_normal_values():
    assert clean_nans({"cost": 0.05}) == {"cost": 0.05}


def make_pydantic_like(**kwargs):
    """Mimic a Pydantic model with model_dump(), without needing the real class."""
    obj = SimpleNamespace(**kwargs)
    obj.model_dump = lambda: kwargs
    return obj


def test_serialize_result_converts_pydantic_issues():
    issue = make_pydantic_like(issue_type="eval_usage", severity="high")
    final_state = {
        "job_id": "job_1",
        "filename": "app.py",
        "language": "python",
        "issues": [issue],
        "fix_proposals": [],
        "severity_counts": {"high": 1},
        "total_cost_usd": 0.05,
        "review_summary": "summary text",
    }
    result = serialize_result(final_state)
    assert result["total_issues"] == 1
    assert result["issues"][0]["issue_type"] == "eval_usage"


def test_serialize_result_accepts_plain_dict_issues():
    final_state = {
        "job_id": "job_2",
        "filename": "app.py",
        "language": "python",
        "issues": [{"issue_type": "bare_except", "severity": "medium"}],
        "fix_proposals": [],
        "severity_counts": {},
        "total_cost_usd": 0.0,
        "review_summary": "",
    }
    result = serialize_result(final_state)
    assert result["total_issues"] == 1
    assert result["issues"][0]["issue_type"] == "bare_except"


def test_serialize_result_rounds_cost():
    final_state = {
        "job_id": "job_3",
        "filename": "app.py",
        "language": "python",
        "issues": [],
        "fix_proposals": [],
        "severity_counts": {},
        "total_cost_usd": 0.123456789,
        "review_summary": "",
    }
    result = serialize_result(final_state)
    assert result["total_cost_usd"] == 0.123457


def test_serialize_result_handles_missing_optional_fields():
    final_state = {"job_id": "job_4"}
    result = serialize_result(final_state)
    assert result["total_issues"] == 0
    assert result["severity_counts"] == {}
    assert result["total_cost_usd"] == 0.0


def test_serialize_result_converts_fix_proposals():
    proposal = make_pydantic_like(issue_title="Fix eval", explanation="use literal_eval")
    final_state = {
        "job_id": "job_5",
        "filename": "app.py",
        "language": "python",
        "issues": [],
        "fix_proposals": [proposal],
        "severity_counts": {},
        "total_cost_usd": 0.0,
        "review_summary": "",
    }
    result = serialize_result(final_state)
    assert len(result["fix_proposals"]) == 1
    assert result["fix_proposals"][0]["issue_title"] == "Fix eval"


import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.responses import JSONResponse
from fastapi import HTTPException

from src.api.routers.reviews import (
    _run_review_task,
    _job_status,
    _job_results,
    submit_review,
    get_status,
    get_results,
    list_jobs,
    submit_sample_review,
    ReviewRequest,
)


@pytest.mark.asyncio
async def test_run_review_task_success_stores_serialized_result_and_marks_completed():
    job_id = str(uuid.uuid4())[:8]
    request = ReviewRequest(filename="app.py", language="python", code="x = 1")
    fake_final_state = {
        "job_id": job_id,
        "filename": "app.py",
        "language": "python",
        "issues": [],
        "fix_proposals": [],
        "severity_counts": {},
        "total_cost_usd": float("nan"),
        "review_summary": "",
    }
    fake_orchestrator = MagicMock()
    fake_orchestrator.review = AsyncMock(return_value=fake_final_state)
    with patch("src.api.routers.reviews.CodeReviewOrchestrator", return_value=fake_orchestrator):
        await _run_review_task(job_id, request)
    assert _job_status[job_id] == "completed"
    assert _job_results[job_id]["total_cost_usd"] == 0.0  # NaN cleaned


@pytest.mark.asyncio
async def test_run_review_task_failure_sets_failed_status_with_error_message():
    job_id = str(uuid.uuid4())[:8]
    request = ReviewRequest(filename="app.py", language="python", code="x = 1")
    fake_orchestrator = MagicMock()
    fake_orchestrator.review = AsyncMock(side_effect=RuntimeError("agent crashed"))
    with patch("src.api.routers.reviews.CodeReviewOrchestrator", return_value=fake_orchestrator):
        await _run_review_task(job_id, request)
    assert _job_status[job_id] == "failed: agent crashed"
    assert job_id not in _job_results


@pytest.mark.asyncio
async def test_submit_review_schedules_task_and_returns_pending_status():
    fake_bg_tasks = MagicMock()
    request = ReviewRequest(filename="test.py", language="python", code="y = 2")
    result = await submit_review(request, fake_bg_tasks)
    assert result["status"] == "pending"
    assert "job_id" in result
    fake_bg_tasks.add_task.assert_called_once()
    args = fake_bg_tasks.add_task.call_args[0]
    assert args[0] is _run_review_task
    assert args[2] is request


@pytest.mark.asyncio
async def test_get_status_raises_404_for_unknown_job():
    with pytest.raises(HTTPException) as exc_info:
        await get_status("nonexistent-job-id")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_status_returns_current_status():
    job_id = str(uuid.uuid4())[:8]
    _job_status[job_id] = "running"
    result = await get_status(job_id)
    assert result == {"job_id": job_id, "status": "running"}


@pytest.mark.asyncio
async def test_get_results_raises_404_for_unknown_job():
    with pytest.raises(HTTPException) as exc_info:
        await get_results("nonexistent-job-id")
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_results_raises_202_when_not_completed():
    job_id = str(uuid.uuid4())[:8]
    _job_status[job_id] = "running"
    with pytest.raises(HTTPException) as exc_info:
        await get_results(job_id)
    assert exc_info.value.status_code == 202


@pytest.mark.asyncio
async def test_get_results_returns_json_response_when_completed():
    job_id = str(uuid.uuid4())[:8]
    _job_status[job_id] = "completed"
    _job_results[job_id] = {"job_id": job_id, "total_issues": 0}
    result = await get_results(job_id)
    assert isinstance(result, JSONResponse)


@pytest.mark.asyncio
async def test_list_jobs_returns_all_tracked_statuses():
    job_id = str(uuid.uuid4())[:8]
    _job_status[job_id] = "pending"
    result = await list_jobs()
    matching = [j for j in result["jobs"] if j["job_id"] == job_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_submit_sample_review_schedules_vulnerable_sample_code():
    fake_bg_tasks = MagicMock()
    result = await submit_sample_review(fake_bg_tasks)
    assert result["status"] == "pending"
    assert "job_id" in result
    fake_bg_tasks.add_task.assert_called_once()
    args = fake_bg_tasks.add_task.call_args[0]
    assert args[0] is _run_review_task
    scheduled_request = args[2]
    assert scheduled_request.filename == "vulnerable_code.py"
    assert "eval(" in scheduled_request.code


def test_serialize_result_accepts_plain_dict_fix_proposals():
    final_state = {
        "job_id": "job_6",
        "filename": "app.py",
        "language": "python",
        "issues": [],
        "fix_proposals": [{"issue_title": "Fix SQL injection", "explanation": "use parameterized queries"}],
        "severity_counts": {},
        "total_cost_usd": 0.0,
        "review_summary": "",
    }
    result = serialize_result(final_state)
    assert len(result["fix_proposals"]) == 1
    assert result["fix_proposals"][0]["issue_title"] == "Fix SQL injection"
