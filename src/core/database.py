from sqlmodel import SQLModel, Field, Column, JSON
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from typing import Optional
import uuid

from src.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


class ReviewJob(SQLModel, table=True):
    """A code review job submitted to the system."""
    __tablename__ = "review_jobs"

    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8], primary_key=True)
    filename: str
    language: str = "python"
    status: str = Field(default="pending")  # pending | running | completed | failed
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    total_cost_usd: float = 0.0
    total_issues: int = 0
    critical_issues: int = 0


class ReviewResult(SQLModel, table=True):
    """Individual issue found during review."""
    __tablename__ = "review_results"

    id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True)
    job_id: str = Field(foreign_key="review_jobs.id", index=True)
    agent: str  # static_analysis | security | test_coverage | fix_proposal
    issue_type: str
    severity: str  # critical | high | medium | low | info
    line_number: Optional[int] = None
    title: str
    description: str
    suggestion: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
