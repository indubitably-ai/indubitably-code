"""Timing helpers for verifying parallel execution in async tests."""
from __future__ import annotations

import time
from datetime import timedelta
from typing import Awaitable, Callable


async def measure_duration(operation: Callable[[], Awaitable[None]]) -> timedelta:
    """Measure how long awaiting *operation* takes."""
    start = time.perf_counter()
    await operation()
    end = time.perf_counter()
    return timedelta(seconds=end - start)


def assert_parallel_execution(duration: timedelta, expected_single: timedelta) -> None:
    """Assert that *duration* is close to a single-task runtime."""
    threshold = expected_single * 1.5
    if duration >= threshold:
        raise AssertionError(
            f"Expected parallel execution (~{expected_single}), observed {duration}"
        )


def assert_serial_execution(duration: timedelta, expected_single: timedelta, count: int) -> None:
    """Assert that *duration* matches serial composition of *count* tasks."""
    threshold = expected_single * (count - 0.5)
    if duration < threshold:
        raise AssertionError(
            f"Expected serial execution (>={threshold}), observed {duration}"
        )


def measure_sync_duration(operation: Callable[[], None]) -> timedelta:
    """Measure duration of a synchronous callable."""
    start = time.perf_counter()
    operation()
    end = time.perf_counter()
    return timedelta(seconds=end - start)
