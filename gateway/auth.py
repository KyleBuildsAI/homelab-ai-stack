"""
homelab-ai-stack Gateway - Authentication Module

Manages API key validation and JWT token generation/verification.
API keys are stored in Redis with metadata (name, created, rate limits).
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import redis.asyncio as aioredis

logger = logging.getLogger("gateway.auth")

# Redis key prefixes
KEY_PREFIX = "hai:apikey:"
KEY_INDEX = "hai:apikeys"


@dataclass
class APIKeyInfo:
    """Metadata associated with an API key."""

    key_id: str
    name: str
    hashed_key: str
    created_at: str
    expires_at: Optional[str] = None
    rate_limit_rpm: Optional[int] = None
    rate_limit_tpm: Optional[int] = None
    enabled: bool = True
    scopes: str = "chat,completions,embeddings"


@dataclass
class TokenPayload:
    """Decoded JWT token payload."""

    key_id: str
    name: str
    scopes: list[str]
    exp: float
    iat: float


class AuthManager:
    """
    Handles API key CRUD operations and JWT token management.

    API keys are stored as Redis hashes:
        hai:apikey:<key_id> -> {name, hashed_key, created_at, ...}

    A Redis set tracks all key IDs:
        hai:apikeys -> {key_id_1, key_id_2, ...}
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        admin_api_key: str,
        jwt_secret: str,
        jwt_expiry_hours: int = 24,
    ) -> None:
        self.redis = redis
        self.admin_api_key = admin_api_key
        self.jwt_secret = jwt_secret
        self.jwt_expiry_hours = jwt_expiry_hours

    # -----------------------------------------------------------------------
    # Key hashing
    # -----------------------------------------------------------------------
    @staticmethod
    def hash_key(api_key: str) -> str:
        """SHA-256 hash of an API key for secure storage."""
        return hashlib.sha256(api_key.encode()).hexdigest()

    # -----------------------------------------------------------------------
    # Admin authentication
    # -----------------------------------------------------------------------
    def is_admin_key(self, api_key: str) -> bool:
        """Check if the provided key is the admin master key."""
        if not self.admin_api_key:
            return False
        return secrets.compare_digest(api_key, self.admin_api_key)

    # -----------------------------------------------------------------------
    # API key CRUD
    # -----------------------------------------------------------------------
    async def create_key(
        self,
        name: str,
        rate_limit_rpm: Optional[int] = None,
        rate_limit_tpm: Optional[int] = None,
        expires_in_days: Optional[int] = None,
        scopes: Optional[list[str]] = None,
    ) -> tuple[str, APIKeyInfo]:
        """
        Generate a new API key and store it in Redis.

        Returns:
            Tuple of (plaintext_key, key_info).  The plaintext key is only
            available at creation time.
        """
        # Generate key: hai-<32 random hex chars>
        raw_key = f"hai-{secrets.token_hex(32)}"
        key_id = secrets.token_hex(8)
        hashed = self.hash_key(raw_key)

        now = datetime.now(timezone.utc)
        expires_at = None
        if expires_in_days:
            expires_at = (now + timedelta(days=expires_in_days)).isoformat()

        info = APIKeyInfo(
            key_id=key_id,
            name=name,
            hashed_key=hashed,
            created_at=now.isoformat(),
            expires_at=expires_at,
            rate_limit_rpm=rate_limit_rpm,
            rate_limit_tpm=rate_limit_tpm,
            enabled=True,
            scopes=",".join(scopes) if scopes else "chat,completions,embeddings",
        )

        # Store in Redis
        redis_key = f"{KEY_PREFIX}{key_id}"
        await self.redis.hset(redis_key, mapping=asdict(info))
        await self.redis.sadd(KEY_INDEX, key_id)

        # Set expiry on the Redis key if the API key has an expiry
        if expires_in_days:
            await self.redis.expire(redis_key, expires_in_days * 86400)

        logger.info("Created API key '%s' (id: %s)", name, key_id)
        return raw_key, info

    async def validate_key(self, api_key: str) -> Optional[APIKeyInfo]:
        """
        Validate an API key and return its metadata if valid.

        Returns None if the key is invalid, disabled, or expired.
        """
        hashed = self.hash_key(api_key)

        # Scan all registered keys to find a match
        key_ids = await self.redis.smembers(KEY_INDEX)
        for key_id in key_ids:
            redis_key = f"{KEY_PREFIX}{key_id}"
            stored_hash = await self.redis.hget(redis_key, "hashed_key")

            if stored_hash and secrets.compare_digest(stored_hash, hashed):
                data = await self.redis.hgetall(redis_key)
                if not data:
                    continue

                info = APIKeyInfo(**data)

                # Check if disabled
                if str(info.enabled).lower() in ("false", "0", "no"):
                    logger.warning("Rejected disabled key: %s", key_id)
                    return None

                # Check expiry
                if info.expires_at:
                    exp = datetime.fromisoformat(info.expires_at)
                    if datetime.now(timezone.utc) > exp:
                        logger.warning("Rejected expired key: %s", key_id)
                        return None

                return info

        return None

    async def revoke_key(self, key_id: str) -> bool:
        """Disable an API key by its ID."""
        redis_key = f"{KEY_PREFIX}{key_id}"
        exists = await self.redis.exists(redis_key)
        if not exists:
            return False

        await self.redis.hset(redis_key, "enabled", "false")
        logger.info("Revoked API key: %s", key_id)
        return True

    async def delete_key(self, key_id: str) -> bool:
        """Permanently delete an API key."""
        redis_key = f"{KEY_PREFIX}{key_id}"
        deleted = await self.redis.delete(redis_key)
        await self.redis.srem(KEY_INDEX, key_id)
        if deleted:
            logger.info("Deleted API key: %s", key_id)
        return bool(deleted)

    async def list_keys(self) -> list[dict]:
        """List all API keys (without the hashed key values)."""
        key_ids = await self.redis.smembers(KEY_INDEX)
        keys = []
        for key_id in sorted(key_ids):
            redis_key = f"{KEY_PREFIX}{key_id}"
            data = await self.redis.hgetall(redis_key)
            if data:
                # Never expose the hashed key
                data.pop("hashed_key", None)
                keys.append(data)
        return keys

    # -----------------------------------------------------------------------
    # JWT tokens
    # -----------------------------------------------------------------------
    def generate_token(self, key_info: APIKeyInfo) -> str:
        """Generate a JWT token from a validated API key."""
        now = time.time()
        payload = {
            "key_id": key_info.key_id,
            "name": key_info.name,
            "scopes": key_info.scopes.split(","),
            "iat": now,
            "exp": now + (self.jwt_expiry_hours * 3600),
        }
        return jwt.encode(payload, self.jwt_secret, algorithm="HS256")

    def verify_token(self, token: str) -> Optional[TokenPayload]:
        """
        Verify and decode a JWT token.

        Returns None if the token is invalid or expired.
        """
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=["HS256"])
            return TokenPayload(
                key_id=payload["key_id"],
                name=payload["name"],
                scopes=payload.get("scopes", []),
                exp=payload["exp"],
                iat=payload["iat"],
            )
        except jwt.ExpiredSignatureError:
            logger.debug("Token expired")
            return None
        except jwt.InvalidTokenError as exc:
            logger.debug("Invalid token: %s", exc)
            return None

    # -----------------------------------------------------------------------
    # Unified auth check
    # -----------------------------------------------------------------------
    async def authenticate(self, auth_header: Optional[str]) -> Optional[APIKeyInfo | TokenPayload]:
        """
        Authenticate a request from its Authorization header.

        Supports:
            - Bearer <jwt_token>
            - Bearer <api_key>
            - Api-Key <api_key>

        Returns the key info / token payload, or None if authentication fails.
        """
        if not auth_header:
            return None

        parts = auth_header.split(" ", 1)
        if len(parts) != 2:
            return None

        scheme, credential = parts

        if scheme.lower() == "bearer":
            # Try JWT first
            token_payload = self.verify_token(credential)
            if token_payload:
                return token_payload

            # Fall back to API key
            return await self.validate_key(credential)

        if scheme.lower() in ("api-key", "apikey"):
            return await self.validate_key(credential)

        return None
