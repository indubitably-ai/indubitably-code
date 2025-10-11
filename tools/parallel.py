"""Parallel execution runtime for tool calls."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict

from .router import ToolCall, ToolRouter


class AsyncRWLock:
    """Simple asyncio-based read/write lock."""

    def __init__(self) -> None:
        self._readers = 0
        self._readers_lock = asyncio.Lock()
        self._resource_lock = asyncio.Lock()

    async def acquire_read(self) -> None:
        async with self._readers_lock:
            self._readers += 1
            if self._readers == 1:
                await self._resource_lock.acquire()

    async def release_read(self) -> None:
        async with self._readers_lock:
            self._readers -= 1
            if self._readers == 0:
                self._resource_lock.release()

    async def acquire_write(self) -> None:
        await self._resource_lock.acquire()

    def release_write(self) -> None:
        self._resource_lock.release()

    def read_lock(self) -> "_ReadGuard":
        return _ReadGuard(self)

    def write_lock(self) -> "_WriteGuard":
        return _WriteGuard(self)


class _ReadGuard:
    def __init__(self, lock: AsyncRWLock) -> None:
        self._lock = lock

    async def __aenter__(self) -> None:
        await self._lock.acquire_read()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._lock.release_read()


class _WriteGuard:
    def __init__(self, lock: AsyncRWLock) -> None:
        self._lock = lock

    async def __aenter__(self) -> None:
        await self._lock.acquire_write()

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self._lock.release_write()


@dataclass
class ToolCallRuntime:
    """Coordinates tool execution with registry and concurrency policies."""

    router: ToolRouter

    def __post_init__(self) -> None:
        self._lock = AsyncRWLock()

    async def execute_tool_call(
        self,
        *,
        session: Any,
        turn_context: Any,
        tracker: Any,
        sub_id: str,
        call: ToolCall,
    ) -> Dict[str, Any]:
        if self.router.tool_supports_parallel(call.tool_name):
            async with self._lock.read_lock():
                return await self.router.dispatch_tool_call(
                    session=session,
                    turn_context=turn_context,
                    tracker=tracker,
                    sub_id=sub_id,
                    call=call,
                )
        async with self._lock.write_lock():
            return await self.router.dispatch_tool_call(
                session=session,
                turn_context=turn_context,
                tracker=tracker,
                sub_id=sub_id,
                call=call,
            )
