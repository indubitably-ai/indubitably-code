"""Parallel execution runtime for tool calls."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Dict
from weakref import WeakKeyDictionary

from .router import ToolCall, ToolRouter


class AsyncRWLock:
    """Simple asyncio-based read/write lock."""

    def __init__(self) -> None:
        self._states: "WeakKeyDictionary[asyncio.AbstractEventLoop, _LockState]" = WeakKeyDictionary()
        self._state_lock = threading.Lock()

    async def acquire_read(self) -> None:
        state = self._get_state(create=True)
        async with state.readers_lock:
            state.readers += 1
            if state.readers == 1:
                await state.resource_lock.acquire()

    async def release_read(self) -> None:
        state = self._get_state(create=False)
        async with state.readers_lock:
            state.readers -= 1
            if state.readers == 0:
                state.resource_lock.release()

    async def acquire_write(self) -> None:
        state = self._get_state(create=True)
        await state.resource_lock.acquire()

    def release_write(self) -> None:
        state = self._get_state(create=False)
        state.resource_lock.release()

    def read_lock(self) -> "_ReadGuard":
        return _ReadGuard(self)

    def write_lock(self) -> "_WriteGuard":
        return _WriteGuard(self)

    def _get_state(self, *, create: bool) -> "_LockState":
        loop = asyncio.get_running_loop()
        state = self._states.get(loop)
        if state is not None:
            return state
        if not create:
            raise RuntimeError("lock state missing for current event loop")
        with self._state_lock:
            state = self._states.get(loop)
            if state is None:
                state = _LockState()
                self._states[loop] = state
        return state


class _LockState:
    __slots__ = ("readers", "readers_lock", "resource_lock")

    def __init__(self) -> None:
        self.readers = 0
        self.readers_lock = asyncio.Lock()
        self.resource_lock = asyncio.Lock()


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
