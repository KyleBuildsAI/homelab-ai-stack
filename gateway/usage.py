"""
homelab-ai-stack Gateway — Usage Tracking

Records per-request usage data (tokens, cost, latency) in SQLite
for analytics and cost monitoring.
"""

from __future__ import annotations

import aiosqlite
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gateway.usage")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id TEXT NOT NULL,
    key_name TEXT DEFAULT '',
    timestamp REAL NOT NULL,
    method TEXT DEFAULT '',
    path TEXT DEFAULT '',
    model TEXT DEFAULT '',
    tokens_in INTEGER DEFAULT 0,
    tokens_out INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    latency_ms REAL DEFAULT 0.0,
    status_code INTEGER DEFAULT 200,
    request_id TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_usage_key ON usage_log(key_id);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage_log(timestamp);
"""


@dataclass
class UsageRecord:
    key_id: str
    key_name: str = ""
    method: str = ""
    path: str = ""
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    status_code: int = 200
    request_id: str = ""


class UsageTracker:
    """SQLite-backed usage tracking for API requests."""

    def __init__(self, db_path: str = "/app/data/usage.db") -> None:
        self.db_path = db_path
        self._db: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.executescript(CREATE_TABLE)
        await self._db.commit()
        logger.info("Usage tracker initialized: %s", self.db_path)

    async def close(self) -> None:
        if self._db:
            await self._db.close()

    async def record(self, rec: UsageRecord) -> None:
        if not self._db:
            return
        await self._db.execute(
            """INSERT INTO usage_log
               (key_id, key_name, timestamp, method, path, model,
                tokens_in, tokens_out, cost_usd, latency_ms,
                status_code, request_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.key_id, rec.key_name, time.time(),
                rec.method, rec.path, rec.model,
                rec.tokens_in, rec.tokens_out, rec.cost_usd,
                rec.latency_ms, rec.status_code, rec.request_id,
            ),
        )
        await self._db.commit()

    async def get_summary(self, key_id: Optional[str] = None) -> dict:
        if not self._db:
            return {}
        where = "WHERE key_id = ?" if key_id else ""
        params = (key_id,) if key_id else ()
        cursor = await self._db.execute(
            f"""SELECT
                COUNT(*) as total_requests,
                COALESCE(SUM(tokens_in), 0) as total_tokens_in,
                COALESCE(SUM(tokens_out), 0) as total_tokens_out,
                COALESCE(SUM(cost_usd), 0) as total_cost,
                COALESCE(AVG(latency_ms), 0) as avg_latency
            FROM usage_log {where}""",
            params,
        )
        row = await cursor.fetchone()
        return {
            "total_requests": row[0],
            "total_tokens_in": row[1],
            "total_tokens_out": row[2],
            "total_cost_usd": round(row[3], 6),
            "avg_latency_ms": round(row[4], 2),
        }

    async def get_recent(self, limit: int = 50) -> list[dict]:
        if not self._db:
            return []
        cursor = await self._db.execute(
            """SELECT key_id, key_name, timestamp, model,
                      tokens_in, tokens_out, cost_usd, latency_ms,
                      status_code
               FROM usage_log ORDER BY timestamp DESC LIMIT ?""",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "key_id": r[0], "key_name": r[1], "timestamp": r[2],
                "model": r[3], "tokens_in": r[4], "tokens_out": r[5],
                "cost_usd": r[6], "latency_ms": r[7], "status_code": r[8],
            }
            for r in rows
        ]
