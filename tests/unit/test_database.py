from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.database import get_session, create_tables, ReviewJob, ReviewResult


@pytest.mark.asyncio
async def test_get_session_yields_a_session_from_the_sessionmaker():
    fake_session = AsyncMock()
    fake_sessionmaker_instance = AsyncMock()
    fake_sessionmaker_instance.__aenter__ = AsyncMock(return_value=fake_session)
    fake_sessionmaker_instance.__aexit__ = AsyncMock(return_value=None)

    with patch("src.core.database.AsyncSessionLocal", return_value=fake_sessionmaker_instance):
        gen = get_session()
        session = await gen.__anext__()
        assert session is fake_session
        # Exhaust the generator to trigger the context manager's exit
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()


@pytest.mark.asyncio
async def test_create_tables_runs_metadata_create_all():
    fake_conn = AsyncMock()
    fake_begin_ctx = AsyncMock()
    fake_begin_ctx.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_begin_ctx.__aexit__ = AsyncMock(return_value=None)

    fake_engine = MagicMock()
    fake_engine.begin = MagicMock(return_value=fake_begin_ctx)

    with patch("src.core.database.engine", fake_engine):
        await create_tables()

    fake_conn.run_sync.assert_awaited_once()


def test_review_job_defaults():
    job = ReviewJob(filename="app.py")
    assert job.language == "python"
    assert job.status == "pending"
    assert job.total_cost_usd == 0.0
    assert job.total_issues == 0
    assert job.critical_issues == 0
    assert job.completed_at is None
    assert len(job.id) == 8


def test_review_result_defaults():
    result = ReviewResult(
        job_id="job_1",
        agent="security",
        issue_type="eval_usage",
        severity="high",
        title="Dangerous eval",
        description="eval() found",
    )
    assert result.line_number is None
    assert result.suggestion is None
    assert result.job_id == "job_1"
