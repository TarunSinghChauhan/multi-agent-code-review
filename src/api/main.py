from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.core.database import create_tables
from src.core.logging import setup_logging, get_logger
from src.api.routers import reviews, health

setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", service="multi-agent-code-review")
    await create_tables()
    yield
    logger.info("shutdown", service="multi-agent-code-review")


app = FastAPI(
    title="Multi-Agent Code Review System",
    description="Autonomous code review using LangGraph multi-agent pipeline",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/health", tags=["Health"])
app.include_router(reviews.router, prefix="/reviews", tags=["Reviews"])
