from datetime import datetime, timedelta, timezone

from src.core.database import ReviewJob, ReviewResult, _utcnow


def _now_naive_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def test_utcnow_returns_naive_value_close_to_current_utc():
    value = _utcnow()
    assert value.tzinfo is None
    assert abs(_now_naive_utc() - value) < timedelta(seconds=5)


def test_review_job_created_at_default_is_naive_utc():
    job = ReviewJob(filename="a.py")
    assert job.created_at.tzinfo is None
    assert abs(_now_naive_utc() - job.created_at) < timedelta(seconds=5)


def test_review_result_created_at_default_is_naive_utc():
    result = ReviewResult(
        job_id="abc12345",
        agent="security",
        issue_type="x",
        severity="low",
        title="t",
        description="d",
    )
    assert result.created_at.tzinfo is None
    assert abs(_now_naive_utc() - result.created_at) < timedelta(seconds=5)
