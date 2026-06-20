"""Health check endpoint."""

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(prefix="/health", tags=["health"])


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    service: str
    checks: dict[str, str]


@router.get("", response_model=HealthResponse)
async def health_check(request: Request) -> HealthResponse:
    """
    Health check endpoint.

    Verifies Redis and Postgres connectivity for orchestrators and load balancers.
    """
    checks: dict[str, str] = {"api": "ok"}
    overall = "healthy"

    redis = getattr(request.app.state, "redis", None)
    if redis is None:
        checks["redis"] = "not_initialized"
        overall = "degraded"
    else:
        try:
            await redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"
            overall = "degraded"

    from backend.db.session import engine

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {exc}"
        overall = "degraded"

    return HealthResponse(
        status=overall,
        service="ai-ticket-assistant-backend",
        checks=checks,
    )
