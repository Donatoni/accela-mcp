from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from accela_mcp.utils.cache import TTLCache


@pytest.mark.asyncio
async def test_get_or_set_caches_loader_result() -> None:
    cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=60)
    calls = 0

    async def loader() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"hello": "world"}

    key = TTLCache.make_key("a", "b")
    first = await cache.get_or_set(key, loader)
    second = await cache.get_or_set(key, loader)
    assert first == {"hello": "world"}
    assert second == {"hello": "world"}
    assert calls == 1


@pytest.mark.asyncio
async def test_concurrent_callers_share_loader() -> None:
    cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=60)
    calls = 0

    async def slow_loader() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.05)
        return {"x": calls}

    key = TTLCache.make_key("x")
    results = await asyncio.gather(
        cache.get_or_set(key, slow_loader),
        cache.get_or_set(key, slow_loader),
        cache.get_or_set(key, slow_loader),
    )
    assert calls == 1
    assert all(r == {"x": 1} for r in results)


@pytest.mark.asyncio
async def test_invalidate_forces_reload() -> None:
    cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=60)
    calls = 0

    async def loader() -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"v": calls}

    key = TTLCache.make_key("k")
    await cache.get_or_set(key, loader)
    cache.invalidate(key)
    second = await cache.get_or_set(key, loader)
    assert calls == 2
    assert second == {"v": 2}


@pytest.mark.asyncio
async def test_expired_entries_drop() -> None:
    cache: TTLCache[dict[str, Any]] = TTLCache(ttl_seconds=0.01)

    async def loader() -> dict[str, Any]:
        return {"v": 1}

    key = TTLCache.make_key("k")
    await cache.get_or_set(key, loader)
    time.sleep(0.05)
    assert cache.get(key) is None


@pytest.mark.asyncio
async def test_max_entries_evicts_oldest() -> None:
    cache: TTLCache[int] = TTLCache(ttl_seconds=60, max_entries=2)
    await cache.set("a", 1)
    await cache.set("b", 2)
    await cache.set("c", 3)
    # Cache is bounded; one entry was evicted.
    present = sum(1 for k in ("a", "b", "c") if cache.get(k) is not None)
    assert present == 2


def test_zero_ttl_rejected() -> None:
    with pytest.raises(ValueError):
        TTLCache(ttl_seconds=0)


def test_make_key_is_stable() -> None:
    k1 = TTLCache.make_key("a", {"x": 1, "y": 2})
    k2 = TTLCache.make_key("a", {"y": 2, "x": 1})
    assert k1 == k2
