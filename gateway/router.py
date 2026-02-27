"""
homelab-ai-stack Gateway — API Routes

Proxy routes that authenticate requests, enforce rate limits, forward
to LiteLLM, and log usage. Also provides admin endpoints for key management.
"""

from __future__ import annotations

import logging
import os
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse

from auth import AuthManager, APIKeyInfo
from models import (
    CreateKeyRequest, CreateKeyResponse, ErrorResponse,
    KeyListItem, TokenRequest, TokenResponse, UsageSummary,
)
from usage import UsageRecord

logger = logging.getLogger("gateway.router")

LITELLM_URL = os.getenv("LITELLM_UPSTREAM_URL", "http://litellm:4000")
LITELLM_KEY = os.getenv("LITELLM_MASTER_KEY", "")
COST_INPUT = float(os.getenv("COST_PER_1K_INPUT_TOKENS", "0"))
COST_OUTPUT = float(os.getenv("COST_PER_1K_OUTPUT_TOKENS", "0"))

api_router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------
async def require_auth(
    request: Request,
    authorization: str = Header(None),
) -> APIKeyInfo:
    auth: AuthManager = request.app.state.auth
    result = await auth.authenticate(authorization)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    if isinstance(result, APIKeyInfo):
        return result
    # TokenPayload — look up the key info
    return APIKeyInfo(
        key_id=result.key_id,
        name=result.name,
        hashed_key="",
        created_at="",
        scopes=",".join(result.scopes),
    )


async def require_admin(
    request: Request,
    authorization: str = Header(None),
) -> None:
    auth: AuthManager = request.app.state.auth
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization")
    credential = authorization.split(" ", 1)[-1]
    if not auth.is_admin_key(credential):
        raise HTTPException(status_code=403, detail="Admin access required")


# ---------------------------------------------------------------------------
# LLM Proxy endpoints
# ---------------------------------------------------------------------------
@api_router.post("/v1/chat/completions", tags=["llm"])
async def chat_completions(
    request: Request,
    key_info: APIKeyInfo = Depends(require_auth),
):
    """Proxy chat completions to LiteLLM with auth and rate limiting."""
    # Rate limit check
    rl = request.app.state.rate_limiter
    rpm_limit = int(key_info.rate_limit_rpm) if key_info.rate_limit_rpm else None
    tpm_limit = int(key_info.rate_limit_tpm) if key_info.rate_limit_tpm else None
    status = await rl.check_request(key_info.key_id, rpm_limit, tpm_limit)

    if not status.allowed:
        block = status.blocking_result
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Retry after {block.retry_after:.0f}s",
            headers=status.headers(),
        )

    body = await request.body()
    start = time.perf_counter()

    async with httpx.AsyncClient(timeout=300) as client:
        headers = {
            "Authorization": f"Bearer {LITELLM_KEY}",
            "Content-Type": "application/json",
        }
        resp = await client.post(
            f"{LITELLM_URL}/v1/chat/completions",
            content=body,
            headers=headers,
        )

    elapsed_ms = (time.perf_counter() - start) * 1000

    # Parse usage from response
    try:
        data = resp.json()
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)
        model = data.get("model", "")
    except Exception:
        tokens_in = tokens_out = 0
        model = ""

    cost = (tokens_in * COST_INPUT + tokens_out * COST_OUTPUT) / 1000

    # Record usage
    tracker = request.app.state.usage_tracker
    await tracker.record(UsageRecord(
        key_id=key_info.key_id,
        key_name=key_info.name,
        method="POST",
        path="/v1/chat/completions",
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost,
        latency_ms=elapsed_ms,
        status_code=resp.status_code,
        request_id=getattr(request.state, "request_id", ""),
    ))

    # Record tokens for TPM tracking
    if tokens_in + tokens_out > 0:
        await rl.record_tokens(key_info.key_id, tokens_in + tokens_out, tpm_limit)

    response = JSONResponse(content=resp.json(), status_code=resp.status_code)
    for k, v in status.headers().items():
        response.headers[k] = v
    return response


@api_router.post("/v1/embeddings", tags=["llm"])
async def embeddings(
    request: Request,
    key_info: APIKeyInfo = Depends(require_auth),
):
    """Proxy embedding requests to LiteLLM."""
    body = await request.body()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{LITELLM_URL}/v1/embeddings",
            content=body,
            headers={
                "Authorization": f"Bearer {LITELLM_KEY}",
                "Content-Type": "application/json",
            },
        )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


@api_router.get("/v1/models", tags=["llm"])
async def list_models(
    request: Request,
    key_info: APIKeyInfo = Depends(require_auth),
):
    """List available models from LiteLLM."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{LITELLM_URL}/v1/models",
            headers={"Authorization": f"Bearer {LITELLM_KEY}"},
        )
    return JSONResponse(content=resp.json(), status_code=resp.status_code)


# ---------------------------------------------------------------------------
# Admin: API Key management
# ---------------------------------------------------------------------------
@api_router.post("/admin/keys", tags=["admin"], response_model=CreateKeyResponse)
async def create_api_key(
    request: Request,
    body: CreateKeyRequest,
    _: None = Depends(require_admin),
):
    auth: AuthManager = request.app.state.auth
    raw_key, info = await auth.create_key(
        name=body.name,
        rate_limit_rpm=body.rate_limit_rpm,
        rate_limit_tpm=body.rate_limit_tpm,
        expires_in_days=body.expires_in_days,
        scopes=body.scopes,
    )
    return CreateKeyResponse(api_key=raw_key, key_id=info.key_id, name=info.name)


@api_router.get("/admin/keys", tags=["admin"])
async def list_api_keys(
    request: Request,
    _: None = Depends(require_admin),
):
    auth: AuthManager = request.app.state.auth
    return await auth.list_keys()


@api_router.delete("/admin/keys/{key_id}", tags=["admin"])
async def revoke_api_key(
    key_id: str,
    request: Request,
    _: None = Depends(require_admin),
):
    auth: AuthManager = request.app.state.auth
    ok = await auth.revoke_key(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"status": "revoked", "key_id": key_id}


# ---------------------------------------------------------------------------
# Admin: Usage
# ---------------------------------------------------------------------------
@api_router.get("/admin/usage", tags=["admin"])
async def get_usage(
    request: Request,
    key_id: str = None,
    _: None = Depends(require_admin),
):
    tracker = request.app.state.usage_tracker
    return await tracker.get_summary(key_id)


@api_router.get("/admin/usage/recent", tags=["admin"])
async def get_recent_usage(
    request: Request,
    limit: int = 50,
    _: None = Depends(require_admin),
):
    tracker = request.app.state.usage_tracker
    return await tracker.get_recent(limit)


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------
@api_router.post("/auth/token", tags=["auth"], response_model=TokenResponse)
async def exchange_token(request: Request, body: TokenRequest):
    auth: AuthManager = request.app.state.auth
    key_info = await auth.validate_key(body.api_key)
    if key_info is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    token = auth.generate_token(key_info)
    return TokenResponse(
        token=token,
        expires_in=auth.jwt_expiry_hours * 3600,
    )
