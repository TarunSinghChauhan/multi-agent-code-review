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

from types import SimpleNamespace

from pydantic import ValidationError

import src.api.routers.reviews as reviews_module
from src.api.routers.reviews import (
    _run_review_task,
    _job_status,
    _job_results,
    _client_ip,
    _enforce_limits,
    _remember,
    limits,
    submit_review,
    get_status,
    get_results,
    submit_sample_review,
    ReviewRequest,
)


def fake_request(ip="10.0.0.1", forwarded=None):
    """Just enough of a starlette Request for the limit helpers."""
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    client = SimpleNamespace(host=ip) if ip else None
    return SimpleNamespace(headers=headers, client=client)


@pytest.fixture(autouse=True)
def _fresh_limiter_state():
    """The rate limiter keeps module-level state; give every test a clean slate."""
    reviews_module._ip_hits.clear()
    reviews_module._daily.update(day="", count=0)
    yield
    reviews_module._ip_hits.clear()
    reviews_module._daily.update(day="", count=0)


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
    # The caller gets a generic message; the real error is only logged.
    assert _job_status[job_id] == "failed: the review could not be completed"
    assert "agent crashed" not in _job_status[job_id]
    assert job_id not in _job_results


@pytest.mark.asyncio
async def test_submit_review_schedules_task_and_returns_pending_status():
    fake_bg_tasks = MagicMock()
    request = ReviewRequest(filename="test.py", language="python", code="y = 2")
    result = await submit_review(request, fake_request(), fake_bg_tasks)
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
async def test_submit_sample_review_schedules_vulnerable_sample_code():
    fake_bg_tasks = MagicMock()
    result = await submit_sample_review(fake_request(), fake_bg_tasks)
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


# ---- public-demo guardrails -------------------------------------------------

def test_client_ip_prefers_the_first_forwarded_address():
    assert _client_ip(fake_request(forwarded="203.0.113.9, 10.1.1.1")) == "203.0.113.9"
    assert _client_ip(fake_request(forwarded="  203.0.113.9  ")) == "203.0.113.9"


def test_client_ip_falls_back_to_the_socket_address_then_unknown():
    assert _client_ip(fake_request(ip="192.0.2.7")) == "192.0.2.7"
    assert _client_ip(fake_request(ip=None)) == "unknown"


def test_per_ip_hourly_limit_blocks_the_next_request(monkeypatch):
    monkeypatch.setattr(reviews_module, "PER_IP_HOURLY_LIMIT", 3)
    for _ in range(3):
        _enforce_limits(fake_request())
    with pytest.raises(HTTPException) as exc:
        _enforce_limits(fake_request())
    assert exc.value.status_code == 429
    assert "Hourly" in exc.value.detail


def test_each_ip_has_its_own_hourly_allowance(monkeypatch):
    monkeypatch.setattr(reviews_module, "PER_IP_HOURLY_LIMIT", 1)
    _enforce_limits(fake_request(ip="10.0.0.1"))
    _enforce_limits(fake_request(ip="10.0.0.2"))  # a different visitor is unaffected
    with pytest.raises(HTTPException):
        _enforce_limits(fake_request(ip="10.0.0.1"))


def test_hourly_allowance_comes_back_after_an_hour(monkeypatch):
    monkeypatch.setattr(reviews_module, "PER_IP_HOURLY_LIMIT", 1)
    now = [1_000_000.0]
    monkeypatch.setattr(reviews_module.time, "time", lambda: now[0])
    _enforce_limits(fake_request())
    now[0] += 3599
    with pytest.raises(HTTPException):
        _enforce_limits(fake_request())
    now[0] += 2  # just past the one-hour window
    _enforce_limits(fake_request())


def test_daily_limit_blocks_everyone_until_the_next_day(monkeypatch):
    monkeypatch.setattr(reviews_module, "DAILY_REVIEW_LIMIT", 2)
    monkeypatch.setattr(reviews_module, "PER_IP_HOURLY_LIMIT", 100)
    monkeypatch.setattr(reviews_module, "_today", lambda: "2026-01-01")
    _enforce_limits(fake_request(ip="10.0.0.1"))
    _enforce_limits(fake_request(ip="10.0.0.2"))
    with pytest.raises(HTTPException) as exc:
        _enforce_limits(fake_request(ip="10.0.0.3"))
    assert exc.value.status_code == 429
    assert "Daily" in exc.value.detail

    monkeypatch.setattr(reviews_module, "_today", lambda: "2026-01-02")
    _enforce_limits(fake_request(ip="10.0.0.3"))  # counter reset with the new day


def test_a_blocked_request_does_not_use_up_the_daily_quota(monkeypatch):
    monkeypatch.setattr(reviews_module, "PER_IP_HOURLY_LIMIT", 1)
    _enforce_limits(fake_request())
    with pytest.raises(HTTPException):
        _enforce_limits(fake_request())
    assert reviews_module._daily["count"] == 1


@pytest.mark.asyncio
async def test_limits_endpoint_reports_the_remaining_daily_quota(monkeypatch):
    monkeypatch.setattr(reviews_module, "DAILY_REVIEW_LIMIT", 10)
    monkeypatch.setattr(reviews_module, "_today", lambda: "2026-01-01")
    _enforce_limits(fake_request())
    out = await limits()
    assert out["daily_limit"] == 10
    assert out["used_today"] == 1
    assert out["remaining_today"] == 9
    assert out["max_code_chars"] == reviews_module.MAX_CODE_CHARS


@pytest.mark.asyncio
async def test_limits_endpoint_shows_zero_used_on_a_new_day(monkeypatch):
    monkeypatch.setattr(reviews_module, "_today", lambda: "2026-01-01")
    _enforce_limits(fake_request())
    monkeypatch.setattr(reviews_module, "_today", lambda: "2026-01-02")
    assert (await limits())["used_today"] == 0


@pytest.mark.asyncio
async def test_a_rate_limited_submit_never_schedules_a_review(monkeypatch):
    monkeypatch.setattr(reviews_module, "PER_IP_HOURLY_LIMIT", 0)
    fake_bg_tasks = MagicMock()
    request = ReviewRequest(code="x = 1")
    with pytest.raises(HTTPException) as exc:
        await submit_review(request, fake_request(), fake_bg_tasks)
    assert exc.value.status_code == 429
    fake_bg_tasks.add_task.assert_not_called()


def test_remember_keeps_only_the_most_recent_jobs(monkeypatch):
    monkeypatch.setattr(reviews_module, "MAX_STORED_JOBS", 3)
    monkeypatch.setattr(reviews_module, "_job_status", {})
    monkeypatch.setattr(reviews_module, "_job_results", {"a": {"x": 1}})
    for job_id in ["a", "b", "c", "d"]:
        _remember(job_id)
    assert list(reviews_module._job_status) == ["b", "c", "d"]
    assert "a" not in reviews_module._job_results  # evicted together with its status
    assert reviews_module._job_status["d"] == "pending"


def test_review_request_rejects_oversized_empty_and_non_python_code():
    with pytest.raises(ValidationError):
        ReviewRequest(code="x" * (reviews_module.MAX_CODE_CHARS + 1))
    with pytest.raises(ValidationError):
        ReviewRequest(code="")
    with pytest.raises(ValidationError):
        ReviewRequest(code="x = 1", language="javascript")
    assert ReviewRequest(code="x" * reviews_module.MAX_CODE_CHARS).language == "python"
