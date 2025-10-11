"""Async testing utilities aligned with codex-rs patterns."""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar

T = TypeVar("T")


def _now() -> float:
    """Return the current event loop time."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.get_event_loop()
    return loop.time()


async def wait_for_condition(
    condition: Callable[[], bool],
    *,
    timeout: timedelta = timedelta(seconds=30),
    poll_interval: timedelta = timedelta(milliseconds=10),
) -> None:
    """Wait until *condition* returns truthy or raise ``TimeoutError``."""
    deadline = _now() + timeout.total_seconds()
    while not condition():
        if _now() > deadline:
            raise TimeoutError("Condition not met within allotted time")
        await asyncio.sleep(poll_interval.total_seconds())


async def wait_for_event(
    event_stream: AsyncIterator[T],
    predicate: Callable[[T], bool],
    *,
    timeout: timedelta = timedelta(seconds=30),
) -> T:
    """Consume *event_stream* until *predicate* matches or time out."""
    deadline = _now() + timeout.total_seconds()
    async for event in event_stream:
        if predicate(event):
            return event
        if _now() > deadline:
            raise TimeoutError("Expected event not received before timeout")
    raise TimeoutError("Event stream exhausted before predicate matched")


async def gather_with_concurrency(
    *aws: Awaitable[T],
    limit: int,
) -> list[T]:
    """Gather awaitables with an optional concurrency limit."""
    semaphore = asyncio.Semaphore(limit)

    async def _run(coro: Awaitable[T]) -> T:
        async with semaphore:
            return await coro

    return await asyncio.gather(*(_run(coro) for coro in aws))
