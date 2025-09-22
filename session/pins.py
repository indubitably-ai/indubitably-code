"""Pin management for persistent prompt inserts."""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional


@dataclass
class Pin:
    identifier: str
    text: str
    created_at: float
    expires_at: Optional[float] = None

    def is_expired(self, *, now: Optional[float] = None) -> bool:
        if self.expires_at is None:
            return False
        current = now or time.time()
        return current >= self.expires_at


class PinManager:
    """Track session pins that bypass compaction."""

    def __init__(self) -> None:
        self._pins: Dict[str, Pin] = {}
        self._id_iter = (f"pin-{n}" for n in itertools.count(1))

    def add_pin(self, text: str, *, ttl_seconds: Optional[int] = None) -> Pin:
        identifier = next(self._id_iter)
        created = time.time()
        expires = created + ttl_seconds if ttl_seconds else None
        pin = Pin(identifier=identifier, text=text.strip(), created_at=created, expires_at=expires)
        if not pin.text:
            raise ValueError("Pin text must not be empty")
        self._pins[pin.identifier] = pin
        return pin

    def remove_pin(self, identifier: str) -> bool:
        return self._pins.pop(identifier, None) is not None

    def clear_expired(self) -> None:
        now = time.time()
        expired = [pid for pid, pin in self._pins.items() if pin.is_expired(now=now)]
        for pid in expired:
            self._pins.pop(pid, None)

    def list_pins(self) -> Iterable[Pin]:
        self.clear_expired()
        return list(self._pins.values())

    def size(self) -> int:
        return len(self._pins)


__all__ = ["Pin", "PinManager"]
