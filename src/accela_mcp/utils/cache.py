"""A small async-safe TTL cache for reference-data endpoints.

Reference data (record types, statuses, departments, fee schedules, etc.)
changes rarely. Caching with a 1-hour TTL eliminates a great deal of needless
chatter without risking stale operational data — record-level state is
deliberately NOT cached here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")


@dataclass
class _Entry(Generic[T]):
    value: T
    expires_at: float


class TTLCache(Generic[T]):
    """Async-safe in-memory TTL cache.

    `get_or_set` is the primary entry point: it returns a cached value if
    fresh, otherwise calls the loader, caches the result, and returns it.
    Concurrent `get_or_set` calls for the same key share one loader call via
    a per-key lock — important under MCP fan-out where two tools may race for
    the same metadata at the same instant.
    """

    def __init__(self, ttl_seconds: float, *, max_entries: int = 1024) -> None:
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        self._ttl = ttl_seconds
        self._max = max_entries
        self._entries: dict[str, _Entry[T]] = {}
        self._global_lock = asyncio.Lock()
        self._key_locks: dict[str, asyncio.Lock] = {}

    @staticmethod
    def make_key(*parts: Any) -> str:
        """Stable string key from arbitrary JSON-serializable parts."""
        payload = json.dumps(parts, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _now(self) -> float:
        return time.monotonic()

    def get(self, key: str) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        if entry.expires_at < self._now():
            self._entries.pop(key, None)
            return None
        return entry.value

    async def set(self, key: str, value: T) -> None:
        async with self._global_lock:
            if len(self._entries) >= self._max:
                # Evict the oldest entry (cheap & adequate at this scale).
                oldest_key = min(self._entries, key=lambda k: self._entries[k].expires_at)
                self._entries.pop(oldest_key, None)
            self._entries[key] = _Entry(value=value, expires_at=self._now() + self._ttl)

    def invalidate(self, key: str) -> None:
        self._entries.pop(key, None)

    def clear(self) -> None:
        self._entries.clear()

    async def get_or_set(self, key: str, loader: Callable[[], Awaitable[T]]) -> T:
        cached = self.get(key)
        if cached is not None:
            return cached

        # Per-key lock so concurrent callers share the loader call.
        async with self._global_lock:
            lock = self._key_locks.setdefault(key, asyncio.Lock())

        async with lock:
            cached = self.get(key)
            if cached is not None:
                return cached
            value = await loader()
            await self.set(key, value)
            return value
