from fastapi import APIRouter
from datetime import datetime, timezone

router = APIRouter()


@router.get("/")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "multi-agent-code-review",
    }
