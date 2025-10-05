"""Prompt packing pipeline built on top of the context session."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Tuple

from session import ContextSession


@dataclass
class PackedPrompt:
    system: List[Dict[str, Any]]
    messages: List[Dict[str, Any]]
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
        system, chat_messages = _split_system_messages(messages)
        status = self.session.status()
        return PackedPrompt(
            system=system,
            messages=chat_messages,
            token_total=status["tokens"],
            window_tokens=status["window"],
        )

    def dry_run(self) -> PackedPrompt:
        return self.pack()


def _split_system_messages(
    messages: Sequence[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    system_blocks: List[Dict[str, Any]] = []
    chat_messages: List[Dict[str, Any]] = []

    for message in messages:
        role = message.get("role")
        content = message.get("content", [])
        if role == "system":
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        system_blocks.append(block)
                    else:
                        system_blocks.append({"type": "text", "text": str(block)})
            elif isinstance(content, str):
                system_blocks.append({"type": "text", "text": content})
            else:
                system_blocks.append({"type": "text", "text": str(content)})
        else:
            chat_messages.append(message)

    return system_blocks, chat_messages


__all__ = ["PromptPacker", "PackedPrompt"]
