"""Async client pooling utilities for MCP server connections."""
from __future__ import annotations

import asyncio
import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional


MCPClientFactory = Callable[[str], Awaitable[Any]]


@dataclass
class _PoolEntry:
    client: Any
    created_at: float
    last_used: float


class MCPClientPool:
    """Maintain a shared pool of MCP clients keyed by server name."""

    def __init__(
        self,
        factory: MCPClientFactory,
        *,
        ttl_seconds: Optional[float] = 300.0,
    ) -> None:
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive or None")
        self._factory = factory
        self._ttl = ttl_seconds
        self._entries: Dict[str, _PoolEntry] = {}
        self._locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def get_client(self, server: str) -> Any:
        """Return a healthy client for *server*, creating one if necessary."""
        lock = await self._get_lock(server)
        async with lock:
            now = time.monotonic()
            entry = self._entries.get(server)
            if entry is not None:
                if self._expired(entry, now):
                    await self._close_client(entry.client)
                    entry = None
                elif not await self._is_healthy(entry.client):
                    await self._close_client(entry.client)
                    entry = None
                else:
                    entry.last_used = now
                    return entry.client

            client = await self._factory(server)
            self._entries[server] = _PoolEntry(client=client, created_at=now, last_used=now)
            return client

    async def mark_unhealthy(self, server: str) -> None:
        """Evict the cached client for *server* after a failure."""
        lock = await self._get_lock(server)
        async with lock:
            entry = self._entries.pop(server, None)
        if entry is not None:
            await self._close_client(entry.client)

    async def shutdown(self) -> None:
        """Close all pooled clients and clear the cache."""
        async with self._global_lock:
            entries = list(self._entries.items())
            self._entries.clear()
        for _server, entry in entries:
            await self._close_client(entry.client)

    async def _get_lock(self, server: str) -> asyncio.Lock:
        async with self._global_lock:
            lock = self._locks.get(server)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[server] = lock
            return lock

    def _expired(self, entry: _PoolEntry, now: float) -> bool:
        if self._ttl is None:
            return False
        return now - entry.last_used > self._ttl

    async def _is_healthy(self, client: Any) -> bool:
        attr = getattr(client, "is_healthy", None)
        if attr is None:
            return True
        result = attr() if callable(attr) else attr
        if inspect.isawaitable(result):  # type: ignore[arg-type]
            try:
                result = await result  # type: ignore[assignment]
            except Exception:
                return False
        return bool(result)

    async def _close_client(self, client: Any) -> None:
        close_coro = None
        for name in ("aclose", "close", "shutdown"):
            fn = getattr(client, name, None)
            if fn is None:
                continue
            try:
                result = fn() if callable(fn) else None
            except Exception:
                continue
            if inspect.isawaitable(result):
                close_coro = result
                break
        if close_coro is not None:
            try:
                await close_coro
            except Exception:
                pass


__all__ = ["MCPClientPool", "MCPClientFactory"]
