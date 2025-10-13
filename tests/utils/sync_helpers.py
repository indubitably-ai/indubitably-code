"""Utilities for coordinating concurrency in tests."""
from __future__ import annotations

import asyncio
from threading import Lock
from typing import Dict


class Barrier:
    """Asynchronous barrier mirroring ``asyncio.Barrier`` semantics."""

    def __init__(self, parties: int) -> None:
        if parties <= 0:
            raise ValueError("Barrier requires at least one participant")
        self._parties = parties
        self._arrived = 0
        self._generation = 0
        self._condition = asyncio.Condition()

    @property
    def parties(self) -> int:
        return self._parties

    async def wait(self) -> int:
        """Wait until *parties* coroutines have reached the barrier."""
        async with self._condition:
            gen = self._generation
            self._arrived += 1
            if self._arrived == self._parties:
                self._generation += 1
                self._arrived = 0
                self._condition.notify_all()
                return 0
            while gen == self._generation:
                await self._condition.wait()
            return self._generation - gen


_barriers: Dict[str, Barrier] = {}
_barriers_lock = Lock()


def get_barrier(identifier: str, parties: int) -> Barrier:
    """Return a named barrier, creating it if necessary."""
    with _barriers_lock:
        barrier = _barriers.get(identifier)
        if barrier is None:
            barrier = Barrier(parties)
            _barriers[identifier] = barrier
        elif barrier.parties != parties:
            raise ValueError(
                f"Barrier '{identifier}' already defined for {barrier.parties} parties (got {parties})"
            )
        return barrier


def clear_barrier(identifier: str) -> None:
    """Remove the named barrier from the registry."""
    with _barriers_lock:
        _barriers.pop(identifier, None)


def reset_barriers() -> None:
    """Remove all barriers (mainly for cleanup hooks)."""
    with _barriers_lock:
        _barriers.clear()
