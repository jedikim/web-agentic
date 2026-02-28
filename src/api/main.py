"""FastAPI application factory for the Evolution API."""
from __future__ import annotations

import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import set_db, set_notifier, set_session_manager
from src.api.routes import evolution, progress, run, scenarios, sessions, versions
from src.api.session_db import SessionDB
from src.api.session_manager import SessionManager
from src.core.config import load_config
from src.core.executor_pool import ExecutorPool
from src.core.selector_cache import SelectorCache
from src.evolution.db import EvolutionDB
from src.evolution.notifier import Notifier
from src.observability.tracing import shutdown as shutdown_tracing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
logging.getLogger("google_genai").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle."""
    # Startup — Evolution
    db = EvolutionDB()
    await db.init()
    set_db(db)

    notifier = Notifier()
    set_notifier(notifier)

    # Startup — Engine config
    engine_config = load_config()

    # Startup — Session infrastructure
    pool = await ExecutorPool.create(headless=True)
    session_db = SessionDB()
    await session_db.init()
    cache = SelectorCache()
    await cache.init()
    session_mgr = SessionManager(
        pool=pool, session_db=session_db, notifier=notifier, cache=cache,
        config=engine_config,
    )
    await session_mgr.start_cleanup_loop()
    set_session_manager(session_mgr)

    logger.info("Evolution API started — DB + Session infrastructure initialized")
    yield

    # Shutdown — Session infrastructure (first)
    await session_mgr.stop_cleanup_loop()
    for sid in list(session_mgr._sessions):
        with contextlib.suppress(Exception):
            await session_mgr.close_session(sid)
    await pool.close()
    await session_db.close()

    # Shutdown — Evolution
    await notifier.close()
    await db.close()
    shutdown_tracing()
    logger.info("Evolution API shutdown complete")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Web-Agentic Evolution API",
        description=(
            "Self-evolving automation engine"
            " — failure analysis, code generation, version management"
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS for evolution-ui dev server
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://localhost:5174",
            "http://localhost:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(evolution.router)
    app.include_router(scenarios.router)
    app.include_router(versions.router)
    app.include_router(progress.router)
    app.include_router(sessions.router)
    app.include_router(run.router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "evolution-api"}

    return app


app = create_app()
