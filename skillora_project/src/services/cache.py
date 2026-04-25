"""
Optional Redis JSON cache helpers.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from redis import Redis

from src.config import CACHE_ENABLED, CACHE_TTL_SECONDS, REDIS_URL

logger = logging.getLogger("services.cache")

_client: Redis | None = None


def _get_client() -> Redis | None:
    global _client

    if not CACHE_ENABLED or not REDIS_URL:
        return None

    if _client is None:
        try:
            _client = Redis.from_url(REDIS_URL, decode_responses=True)
            _client.ping()
        except Exception as exc:
            logger.warning(f"Redis cache disabled: {exc}")
            _client = None
    return _client


def get_json(key: str) -> dict[str, Any] | None:
    client = _get_client()
    if not client:
        return None
    raw = client.get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def set_json(key: str, payload: dict[str, Any], ttl: int = CACHE_TTL_SECONDS) -> None:
    client = _get_client()
    if not client:
        return
    client.setex(key, ttl, json.dumps(payload, ensure_ascii=False))


def delete_key(key: str) -> None:
    client = _get_client()
    if not client:
        return
    client.delete(key)
