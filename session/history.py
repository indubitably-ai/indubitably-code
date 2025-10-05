"""Session history tracking for prompt assembly and compaction."""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .token_meter import TokenMeter


@dataclass
class MessageRecord:
    role: str
    content: List[Dict[str, Any]]
    kind: str
    turn_id: int
    priority: int
    tokens: int
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    compact_content: Optional[List[Dict[str, Any]]] = None
    compact_tokens: Optional[int] = None

    @property
    def effective_content(self) -> List[Dict[str, Any]]:
        return self.compact_content or self.content

    @property
    def effective_tokens(self) -> int:
        return self.compact_tokens if self.compact_tokens is not None else self.tokens

    def text_fragments(self) -> List[str]:
        fragments: List[str] = []
        for block in self.content:
            if block.get("type") == "text":
                fragments.append(block.get("text", ""))
            elif block.get("type") == "tool_result":
                fragments.append(str(block.get("content", "")))
        return fragments


class HistoryStore:
    """Maintain ordered Anthropic-style messages with compaction metadata."""

    def __init__(self, meter: TokenMeter) -> None:
        self._meter = meter
        self._messages: List[MessageRecord] = []
        self._turn_counter = 0
        self._summary_record: Optional[MessageRecord] = None
        self._tool_hashes: Dict[str, MessageRecord] = {}
        self._last_compaction_timestamp: Optional[float] = None

    @property
    def turn_counter(self) -> int:
        return self._turn_counter

    @property
    def summary_record(self) -> Optional[MessageRecord]:
        return self._summary_record

    @property
    def last_compaction_timestamp(self) -> Optional[float]:
        return self._last_compaction_timestamp

    def messages(self) -> List[Dict[str, Any]]:
        return [
            {"role": record.role, "content": record.effective_content}
            for record in self._messages
        ]

    def raw_records(self) -> Iterable[MessageRecord]:
        return list(self._messages)

    def total_tokens(self) -> int:
        return sum(record.effective_tokens for record in self._messages)

    def register_system(self, text: str, *, priority: int = 0) -> MessageRecord:
        message = self._build_message(
            role="system",
            content=[{"type": "text", "text": text}],
            kind="system",
            priority=priority,
            turn_id=0,
        )
        self._messages.insert(0, message)
        return message

    def register_user(self, text: str, *, priority: int = 0) -> MessageRecord:
        self._turn_counter += 1
        message = self._build_message(
            role="user",
            content=[{"type": "text", "text": text}],
            kind="user",
            priority=priority,
            turn_id=self._turn_counter,
        )
        self._messages.append(message)
        return message

    def register_assistant(self, blocks: List[Dict[str, Any]], *, priority: int = 1) -> MessageRecord:
        message = self._build_message(
            role="assistant",
            content=blocks,
            kind="assistant",
            priority=priority,
            turn_id=self._turn_counter,
        )
        self._messages.append(message)
        return message

    def register_tool_results(
        self,
        tool_blocks: List[Dict[str, Any]],
        *,
        priority: int = 1,
    ) -> MessageRecord:
        message = self._build_message(
            role="user",
            content=tool_blocks,
            kind="tool_result",
            priority=priority,
            turn_id=self._turn_counter,
        )
        self._messages.append(message)
        return message

    def register_summary(
        self,
        text: str,
        *,
        turn_id: int,
        priority: int = 1,
    ) -> MessageRecord:
        summary_content = [{"type": "text", "text": text}]
        message = self._build_message(
            role="assistant",
            content=summary_content,
            kind="summary",
            priority=priority,
            turn_id=turn_id,
        )
        self._summary_record = message
        return message

    def remove_records(self, predicate) -> None:
        self._messages = [record for record in self._messages if not predicate(record)]
        self._rebuild_tool_hashes()

    def ensure_summary_index(self) -> Optional[int]:
        if not self._summary_record:
            return None
        for idx, record in enumerate(self._messages):
            if record is self._summary_record:
                return idx
        return None

    def upsert_summary(self, text: str, *, turn_id: int, priority: int = 1) -> MessageRecord:
        if self._summary_record is not None:
            self._summary_record.content[0]["text"] = text
            tokens = self._meter.estimate_messages(
                [{"role": "assistant", "content": self._summary_record.content}]
            )
            self._summary_record.tokens = tokens
            self._summary_record.compact_content = None
            self._summary_record.compact_tokens = None
            self._summary_record.priority = priority
            self._summary_record.turn_id = turn_id
            return self._summary_record
        summary = self.register_summary(text, turn_id=turn_id, priority=priority)
        self._messages.append(summary)
        return summary

    def compact_summary(self, text: str, *, turn_id: int, priority: int = 1) -> None:
        summary = self.upsert_summary(text, turn_id=turn_id, priority=priority)
        self._summary_record = summary
        self._last_compaction_timestamp = time.time()

    def reposition_summary(self, index: int) -> None:
        if not self._summary_record:
            return
        try:
            self._messages.remove(self._summary_record)
        except ValueError:
            pass
        index = max(0, min(index, len(self._messages)))
        self._messages.insert(index, self._summary_record)

    def drop_turns_before(self, turn_id: int) -> None:
        self._messages = [
            record
            for record in self._messages
            if record.kind == "system" or record.turn_id >= turn_id or record is self._summary_record
        ]
        self._rebuild_tool_hashes()

    def rollback_current_turn(self) -> None:
        if self._turn_counter <= 0:
            return
        turn_id = self._turn_counter
        self._messages = [
            record
            for record in self._messages
            if record.turn_id != turn_id or record.kind == "system"
        ]
        self._turn_counter = max(0, self._turn_counter - 1)
        self._rebuild_tool_hashes()

    def set_compacted_content(self, record: MessageRecord, *, text: str) -> None:
        if record.kind == "tool_result" and record.content:
            compact_content = []
            for block in record.content:
                if block.get("type") == "tool_result":
                    new_block = dict(block)
                    new_block["content"] = text
                    compact_content.append(new_block)
                else:
                    compact_content.append({"type": "text", "text": text})
        else:
            compact_content = [{"type": "text", "text": text}]

        tokens = self._meter.estimate_messages(
            [{"role": record.role, "content": compact_content}]
        )
        record.compact_content = compact_content
        record.compact_tokens = tokens

    def clear_compacted_content(self, record: MessageRecord) -> None:
        record.compact_content = None
        record.compact_tokens = None

    def register_tool_hash(self, payload: str, record: MessageRecord) -> None:
        digest = self._tool_digest(payload)
        record.metadata["tool_hash"] = digest
        self._tool_hashes[digest] = record

    def has_tool_hash(self, payload: str) -> bool:
        digest = self._tool_digest(payload)
        return digest in self._tool_hashes

    def _rebuild_tool_hashes(self) -> None:
        self._tool_hashes = {}
        for record in self._messages:
            if record.kind != "tool_result":
                continue
            digest = record.metadata.get("tool_hash")
            if not digest:
                payload = str(record.content)
                digest = self._tool_digest(payload)
                record.metadata["tool_hash"] = digest
            self._tool_hashes[digest] = record

    @staticmethod
    def _tool_digest(payload: str) -> str:
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _build_message(
        self,
        *,
        role: str,
        content: List[Dict[str, Any]],
        kind: str,
        priority: int,
        turn_id: int,
    ) -> MessageRecord:
        tokens = self._meter.estimate_messages(
            [{"role": role, "content": content}],
            label=f"{role}:{kind}",
        )
        return MessageRecord(
            role=role,
            content=content,
            kind=kind,
            turn_id=turn_id,
            priority=priority,
            tokens=tokens,
        )


__all__ = ["HistoryStore", "MessageRecord"]
