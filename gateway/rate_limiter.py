"""
homelab-ai-stack Gateway - Token Bucket Rate Limiter

Redis-backed rate limiting with two independent buckets per API key:
  - RPM (requests per minute)
  - TPM (tokens per minute)

Uses a sliding window approach implemented via Redis sorted sets for
accurate rate limiting that does not suffer from boundary issues.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger("gateway.rate_limiter")

# Redis key prefixes
RPM_PREFIX = "hai:ratelimit:rpm:"
TPM_PREFIX = "hai:ratelimit:tpm:"

# Sliding window duration in seconds
WINDOW_SECONDS = 60


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    limit: int
    remaining: int
    reset_at: float
    retry_after: Optional[float] = None
    bucket: str = ""


@dataclass
class RateLimitStatus:
    """Combined rate limit status for RPM and TPM."""

    rpm: RateLimitResult
    tpm: RateLimitResult

    @property
    def allowed(self) -> bool:
        return self.rpm.allowed and self.tpm.allowed

    @property
    def blocking_result(self) -> Optional[RateLimitResult]:
        """Return the result that is blocking, if any."""
        if not self.rpm.allowed:
            return self.rpm
        if not self.tpm.allowed:
            return self.tpm
        return None

    def headers(self) -> dict[str, str]:
        """Generate rate-limit response headers."""
        return {
            "X-RateLimit-Limit-RPM": str(self.rpm.limit),
            "X-RateLimit-Remaining-RPM": str(max(0, self.rpm.remaining)),
            "X-RateLimit-Reset-RPM": f"{self.rpm.reset_at:.0f}",
            "X-RateLimit-Limit-TPM": str(self.tpm.limit),
            "X-RateLimit-Remaining-TPM": str(max(0, self.tpm.remaining)),
            "X-RateLimit-Reset-TPM": f"{self.tpm.reset_at:.0f}",
        }


class RateLimiter:
    """
    Sliding-window rate limiter backed by Redis sorted sets.

    Each request is recorded as a member of a sorted set with the current
    timestamp as the score.  To check the rate, we count members within
    the last WINDOW_SECONDS.  Expired entries are pruned on each check.

    Two independent limits are enforced:
      - RPM: requests per minute (1 unit per request)
      - TPM: tokens per minute (N units per request, based on token count)
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        default_rpm: int = 60,
        default_tpm: int = 100_000,
    ) -> None:
        self.redis = redis
        self.default_rpm = default_rpm
        self.default_tpm = default_tpm

    async def _check_bucket(
        self,
        key: str,
        limit: int,
        cost: int = 1,
    ) -> RateLimitResult:
        """
        Check and update a single rate limit bucket.

        Args:
            key: Redis key for this bucket.
            limit: Maximum allowed units in the window.
            cost: Number of units this request consumes.

        Returns:
            RateLimitResult indicating whether the request is allowed.
        """
        now = time.time()
        window_start = now - WINDOW_SECONDS

        pipe = self.redis.pipeline(transaction=True)

        # Remove expired entries
        pipe.zremrangebyscore(key, 0, window_start)

        # Count current usage
        pipe.zcard(key)

        # Execute cleanup and count
        results = await pipe.execute()
        current_count = results[1]

        reset_at = now + WINDOW_SECONDS
        remaining = limit - current_count

        if current_count + cost > limit:
            # Rate limit exceeded
            # Find when the oldest entry in the window will expire
            oldest = await self.redis.zrange(key, 0, 0, withscores=True)
            retry_after = WINDOW_SECONDS
            if oldest:
                retry_after = max(0, oldest[0][1] + WINDOW_SECONDS - now)

            logger.warning(
                "Rate limit exceeded on %s: %d/%d (cost=%d)",
                key,
                current_count,
                limit,
                cost,
            )
            return RateLimitResult(
                allowed=False,
                limit=limit,
                remaining=max(0, remaining),
                reset_at=reset_at,
                retry_after=retry_after,
                bucket=key,
            )

        # Record this request - use timestamp + random suffix to allow
        # multiple entries at the same timestamp
        import secrets
        member = f"{now}:{secrets.token_hex(4)}"
        pipe2 = self.redis.pipeline(transaction=True)
        # Add `cost` number of entries (each counts as 1 unit)
        for i in range(cost):
            pipe2.zadd(key, {f"{member}:{i}": now})
        # Set TTL so keys auto-expire
        pipe2.expire(key, WINDOW_SECONDS + 10)
        await pipe2.execute()

        return RateLimitResult(
            allowed=True,
            limit=limit,
            remaining=max(0, remaining - cost),
            reset_at=reset_at,
            bucket=key,
        )

    async def check_request(
        self,
        key_id: str,
        rpm_limit: Optional[int] = None,
        tpm_limit: Optional[int] = None,
    ) -> RateLimitStatus:
        """
        Check RPM rate limit for a request (before processing).

        This should be called before forwarding the request to the upstream.
        Token-based limits (TPM) are checked separately after the response
        is received and the token count is known.

        Args:
            key_id: The API key identifier.
            rpm_limit: Per-key RPM override, or None for default.
            tpm_limit: Per-key TPM override, or None for default.
        """
        rpm = rpm_limit or self.default_rpm
        tpm = tpm_limit or self.default_tpm

        rpm_result = await self._check_bucket(
            key=f"{RPM_PREFIX}{key_id}",
            limit=rpm,
            cost=1,
        )

        # For the pre-request check, we just verify TPM headroom exists
        # (cost=0 check - actual tokens are recorded post-response)
        tpm_key = f"{TPM_PREFIX}{key_id}"
        now = time.time()
        window_start = now - WINDOW_SECONDS
        await self.redis.zremrangebyscore(tpm_key, 0, window_start)
        current_tokens = await self.redis.zcard(tpm_key)

        tpm_result = RateLimitResult(
            allowed=current_tokens < tpm,
            limit=tpm,
            remaining=max(0, tpm - current_tokens),
            reset_at=now + WINDOW_SECONDS,
            bucket=tpm_key,
        )
        if not tpm_result.allowed:
            oldest = await self.redis.zrange(tpm_key, 0, 0, withscores=True)
            if oldest:
                tpm_result.retry_after = max(0, oldest[0][1] + WINDOW_SECONDS - now)

        return RateLimitStatus(rpm=rpm_result, tpm=tpm_result)

    async def record_tokens(
        self,
        key_id: str,
        token_count: int,
        tpm_limit: Optional[int] = None,
    ) -> RateLimitResult:
        """
        Record token usage after a response is received.

        This updates the TPM bucket with the actual number of tokens consumed.
        Called post-response so it does not block the request.

        Args:
            key_id: The API key identifier.
            token_count: Total tokens (input + output) consumed.
            tpm_limit: Per-key TPM override, or None for default.
        """
        if token_count <= 0:
            tpm = tpm_limit or self.default_tpm
            return RateLimitResult(
                allowed=True,
                limit=tpm,
                remaining=tpm,
                reset_at=time.time() + WINDOW_SECONDS,
            )

        return await self._check_bucket(
            key=f"{TPM_PREFIX}{key_id}",
            limit=tpm_limit or self.default_tpm,
            cost=token_count,
        )

    async def get_status(self, key_id: str) -> RateLimitStatus:
        """Get current rate limit status without consuming any quota."""
        now = time.time()
        window_start = now - WINDOW_SECONDS

        rpm_key = f"{RPM_PREFIX}{key_id}"
        tpm_key = f"{TPM_PREFIX}{key_id}"

        pipe = self.redis.pipeline(transaction=True)
        pipe.zremrangebyscore(rpm_key, 0, window_start)
        pipe.zcard(rpm_key)
        pipe.zremrangebyscore(tpm_key, 0, window_start)
        pipe.zcard(tpm_key)
        results = await pipe.execute()

        rpm_count = results[1]
        tpm_count = results[3]

        return RateLimitStatus(
            rpm=RateLimitResult(
                allowed=rpm_count < self.default_rpm,
                limit=self.default_rpm,
                remaining=max(0, self.default_rpm - rpm_count),
                reset_at=now + WINDOW_SECONDS,
            ),
            tpm=RateLimitResult(
                allowed=tpm_count < self.default_tpm,
                limit=self.default_tpm,
                remaining=max(0, self.default_tpm - tpm_count),
                reset_at=now + WINDOW_SECONDS,
            ),
        )
