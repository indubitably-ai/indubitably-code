"""Prompt packing pipeline built on top of the context session."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

from session import ContextSession


@dataclass
class PackedPrompt:
    messages: List[dict]
    token_total: int
    window_tokens: int

    @property
    def usage_pct(self) -> float:
        if not self.window_tokens:
            return 0.0
        return round(self.token_total / self.window_tokens * 100, 2)


class PromptPacker:
    def __init__(self, session: ContextSession) -> None:
        self.session = session

    def pack(self) -> PackedPrompt:
        messages = self.session.build_messages()
        status = self.session.status()
        return PackedPrompt(
            messages=messages,
            token_total=status["tokens"],
            window_tokens=status["window"],
        )

    def dry_run(self) -> PackedPrompt:
        return self.pack()


__all__ = ["PromptPacker", "PackedPrompt"]
