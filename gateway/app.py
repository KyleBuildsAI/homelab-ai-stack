"""
homelab-ai-stack Gateway — FastAPI Application

Central authentication, rate-limiting, and usage-tracking proxy that sits
between clients and LiteLLM.  All API requests flow through this gateway
before reaching the LLM backend.

Architecture:
    Client --[API key]--> Gateway --[master key]--> LiteLLM --> Ollama
"""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from auth import AuthManager
from models import HealthResponse, ErrorResponse
from rate_limiter import RateLimiter
from router import api_router
from usage import UsageTracker

# ---------------------------------------------------------------------------
# Configuration from environment
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("GATEWAY_LOG_LEVEL", "info").upper()
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
ADMIN_API_KEY = os.getenv("GATEWAY_ADMIN_API_KEY", "")
JWT_SECRET = os.getenv("GATEWAY_JWT_SECRET", "")
JWT_EXPIRY_HOURS = int(os.getenv("GATEWAY_JWT_EXPIRY_HOURS", "24"))
RATE_LIMIT_RPM = int(os.getenv("RATE_LIMIT_RPM", "60"))
RATE_LIMIT_TPM = int(os.getenv("RATE_LIMIT_TPM", "100000"))
HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")
PORT = int(os.getenv("GATEWAY_PORT", "8080"))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("gateway")


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown hooks
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Initialize shared resources on startup, clean up on shutdown."""
    logger.info("Starting homelab-ai-stack gateway...")

    # Redis connection pool
    app.state.redis = aioredis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    try:
        await app.state.redis.ping()
        logger.info("Redis connection established: %s", REDIS_URL)
    except Exception as exc:
        logger.error("Redis connection failed: %s", exc)
        raise

    # Auth manager
    app.state.auth = AuthManager(
        redis=app.state.redis,
        admin_api_key=ADMIN_API_KEY,
        jwt_secret=JWT_SECRET,
        jwt_expiry_hours=JWT_EXPIRY_HOURS,
    )

    # Rate limiter
    app.state.rate_limiter = RateLimiter(
        redis=app.state.redis,
        default_rpm=RATE_LIMIT_RPM,
        default_tpm=RATE_LIMIT_TPM,
    )

    # Usage tracker
    app.state.usage_tracker = UsageTracker(db_path="/app/data/usage.db")
    await app.state.usage_tracker.initialize()

    logger.info(
        "Gateway ready — rate limits: %d RPM / %d TPM",
        RATE_LIMIT_RPM,
        RATE_LIMIT_TPM,
    )

    yield  # Application runs

    # Shutdown
    logger.info("Shutting down gateway...")
    await app.state.redis.close()
    await app.state.usage_tracker.close()
    logger.info("Gateway stopped.")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Homelab AI Gateway",
    description=(
        "Authentication, rate-limiting, and usage-tracking gateway for "
        "the homelab-ai-stack.  Proxies OpenAI-compatible requests to "
        "LiteLLM after enforcing access controls."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request timing middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def timing_middleware(request: Request, call_next) -> Response:
    """Add X-Process-Time header to every response."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    response.headers["X-Process-Time"] = f"{elapsed:.4f}"
    return response


# ---------------------------------------------------------------------------
# Request ID middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def request_id_middleware(request: Request, call_next) -> Response:
    """Propagate or generate a request ID for tracing."""
    import uuid

    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------------------
# Health endpoint (unauthenticated)
# ---------------------------------------------------------------------------
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Health check",
)
async def health_check(request: Request) -> HealthResponse:
    """Return service health and dependency status."""
    redis_ok = False
    try:
        await request.app.state.redis.ping()
        redis_ok = True
    except Exception:
        pass

    return HealthResponse(
        status="healthy" if redis_ok else "degraded",
        version="1.0.0",
        redis_connected=redis_ok,
    )


# ---------------------------------------------------------------------------
# Root redirect
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def root() -> JSONResponse:
    """Redirect root to documentation."""
    return JSONResponse(
        content={
            "service": "homelab-ai-stack gateway",
            "version": "1.0.0",
            "docs": "/docs",
            "health": "/health",
        }
    )


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions and return a clean JSON error."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            message="An unexpected error occurred.",
        ).model_dump(),
    )


# ---------------------------------------------------------------------------
# Include API routes
# ---------------------------------------------------------------------------
app.include_router(api_router)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
        reload=False,
        workers=1,
    )
