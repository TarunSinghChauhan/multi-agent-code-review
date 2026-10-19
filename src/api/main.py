from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from src.core.database import create_tables
from src.core.logging import setup_logging, get_logger
from src.api.routers import reviews, health

setup_logging()
logger = get_logger(__name__)

_INDEX_PATH = Path(__file__).resolve().parent.parent / "static" / "index.html"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("startup", service="multi-agent-code-review")
    try:
        await create_tables()
    except Exception as exc:
        # The review pipeline works without the database; metadata saving is best-effort.
        logger.warning("database_unavailable", error=str(exc))
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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    return HTMLResponse(_INDEX_PATH.read_text(encoding="utf-8"))
