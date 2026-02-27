"""
Pydantic models for gateway request/response schemas.
"""

from pydantic import BaseModel, Field
from typing import Any, Optional


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str = "1.0.0"
    redis_connected: bool = True


class ErrorResponse(BaseModel):
    error: str
    message: str
    request_id: Optional[str] = None


class CreateKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    rate_limit_rpm: Optional[int] = Field(None, ge=1, le=10000)
    rate_limit_tpm: Optional[int] = Field(None, ge=1, le=10_000_000)
    expires_in_days: Optional[int] = Field(None, ge=1, le=3650)
    scopes: Optional[list[str]] = None


class CreateKeyResponse(BaseModel):
    api_key: str
    key_id: str
    name: str
    message: str = "Store this key securely — it cannot be retrieved later."


class KeyListItem(BaseModel):
    key_id: str
    name: str
    created_at: str
    enabled: str
    scopes: str
    rate_limit_rpm: Optional[str] = None
    rate_limit_tpm: Optional[str] = None


class TokenRequest(BaseModel):
    api_key: str


class TokenResponse(BaseModel):
    token: str
    expires_in: int
    token_type: str = "Bearer"


class UsageSummary(BaseModel):
    key_id: str
    total_requests: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_cost_usd: float = 0.0
    period: str = "all_time"
