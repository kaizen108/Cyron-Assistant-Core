"""FastAPI backend application entry point."""

import asyncio
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager

# Add project root to Python path
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from backend.config import config
from backend.api import health, relay, knowledge, usage, guilds, auth, bot_internal
from backend.api import panels as panels_router
from backend.api import contexts as contexts_router
from backend.db.session import async_session_factory, engine, init_db
from backend.services.reset_service import run_daily_reset, run_monthly_reset
from backend.utils.embeddings import warmup_embeddings

# Structlog configuration
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logging.basicConfig(level=getattr(logging, config.log_level))


async def _connect_with_retries(
    log: structlog.BoundLogger,
    name: str,
    max_attempts: int,
    interval: float,
    connect_fn,
):
    """Retry an async connect/init so startup survives transient failures."""
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            await connect_fn()
            return
        except Exception as e:
            last_error = e
            log.warning(
                "startup_retry",
                service=name,
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(e),
            )
            if attempt < max_attempts:
                await asyncio.sleep(interval)
    if last_error:
        err_msg = str(last_error)
        hint = "Check DATABASE_URL/POSTGRES_PASSWORD if service=db, or REDIS_URL if service=redis."
        if "InvalidPasswordError" in type(last_error).__name__ or "password authentication failed" in err_msg:
            hint = (
                "Postgres password mismatch: POSTGRES_PASSWORD in .env must match the password "
                "used when the Postgres volume was first created (often 'postgres'). "
                "Either set POSTGRES_PASSWORD to that value, or remove the postgres volume to re-initialize (data loss)."
            )
        log.error("startup_failed", service=name, error=err_msg, hint=hint)
        raise last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: DB, Redis, migrations, scheduler."""
    from alembic.config import Config
    from alembic import command

    log = structlog.get_logger()
    log.info("phase", msg="Starting AI Ticket Assistant Backend")

    # Redis (retry so we tolerate brief unavailability after compose up)
    redis = Redis.from_url(config.redis_url, decode_responses=True)

    async def connect_redis():
        await redis.ping()

    await _connect_with_retries(log, "redis", max_attempts=10, interval=2.0, connect_fn=connect_redis)
    app.state.redis = redis
    log.info("redis_connected")

    # Database (retry so we tolerate Postgres not quite ready)
    async def connect_db():
        await init_db()

    await _connect_with_retries(log, "db", max_attempts=10, interval=2.0, connect_fn=connect_db)
    log.info("db_initialized")

    # Warm up sentence-transformer model at startup so first knowledge insert
    # does not block for 30-60s during lazy model load.
    try:
        await asyncio.to_thread(warmup_embeddings)
        log.info("embeddings_warmed")
    except Exception as e:
        # Best-effort optimization only; do not block API startup.
        log.warning("embeddings_warmup_failed", error=str(e))

    # Scheduler for daily/monthly resets
    scheduler = AsyncIOScheduler()
    async def daily_job() -> None:
        async with async_session_factory() as session:
            await run_daily_reset(session, redis)

    async def monthly_job() -> None:
        async with async_session_factory() as session:
            await run_monthly_reset(session, redis)
    scheduler.add_job(
        daily_job,
        CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="daily_reset",
    )
    scheduler.add_job(
        monthly_job,
        CronTrigger(day=1, hour=0, minute=0, timezone="UTC"),
        id="monthly_reset",
    )
    scheduler.start()
    app.state.scheduler = scheduler
    log.info("scheduler_started")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
    await redis.aclose()
    await engine.dispose()
    log.info("phase", msg="Shutdown complete")


app = FastAPI(
    title="AI Ticket Assistant Backend",
    description="Backend API for AI-powered Discord ticket support bot",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.frontend_allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(bot_internal.router)
app.include_router(guilds.router)
app.include_router(knowledge.router)
app.include_router(usage.router)
app.include_router(relay.router)
app.include_router(panels_router.router)
app.include_router(contexts_router.router)


@app.get("/")
async def root():
    return {"service": "AI Ticket Assistant Backend", "version": "0.2.0", "status": "running"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=config.host,
        port=config.port,
        reload=True,
        log_level=config.log_level.lower(),
    )

