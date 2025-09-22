"""Token estimation utilities with best-effort model mapping."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable, List, Optional

try:  # optional dependency; anthopic SDK does not expose tokenizer helpers locally.
    import tiktoken
except Exception:  # pragma: no cover - fallback path
    tiktoken = None  # type: ignore


_ENCODER_ALIASES = {
    "gpt-4.1": "gpt-4o-mini",
    "gpt-4.1-mini": "gpt-4o-mini",
    "gpt-4o": "gpt-4o-mini",
    "claude-3-7-sonnet-latest": "gpt-4o-mini",
}


@dataclass
class TokenMeasurement:
    label: str
    tokens: int


class TokenMeter:
    """Estimate token consumption for messages and context blocks."""

    def __init__(self, model: str, *, fallback_chars_per_token: int = 4) -> None:
        self.model = model
        self._encoder = _load_encoder(model)
        self._fallback_ratio = max(fallback_chars_per_token, 1)
        self.measurements: List[TokenMeasurement] = []

    def estimate_text(self, text: str, *, label: Optional[str] = None) -> int:
        tokens = self._encode_length(text)
        if label:
            self.measurements.append(TokenMeasurement(label=label, tokens=tokens))
        return tokens

    def estimate_messages(self, messages: Iterable[dict[str, Any]], *, label: Optional[str] = None) -> int:
        total = 0
        for message in messages:
            total += self._estimate_message(message)
        if label:
            self.measurements.append(TokenMeasurement(label=label, tokens=total))
        return total

    def reset_measurements(self) -> None:
        self.measurements.clear()

    def _estimate_message(self, message: dict[str, Any]) -> int:
        role = message.get("role", "")
        overhead = 4  # role + separators heuristic
        total = overhead
        for block in message.get("content", []):
            btype = block.get("type")
            if btype == "text":
                total += self._encode_length(block.get("text", ""))
            elif btype == "tool_use":
                payload = block.get("input", {})
                total += self._encode_length(str(payload))
                total += 6  # account for ids/names overhead
            elif btype == "tool_result":
                total += self._encode_length(str(block.get("content", "")))
                total += 6
            else:
                total += 3
        total += len(role)
        return total

    def _encode_length(self, text: str) -> int:
        if not text:
            return 0
        if self._encoder is None:
            # Cheap heuristic: tokens ~= ceil(chars / ratio)
            return max(1, math.ceil(len(text) / self._fallback_ratio))
        try:
            return len(self._encoder.encode(text))
        except Exception:  # pragma: no cover - fallback when encoder fails
            return max(1, math.ceil(len(text) / self._fallback_ratio))


def _load_encoder(model: str):
    if tiktoken is None:  # pragma: no cover - absence of optional dep
        return None
    target = _ENCODER_ALIASES.get(model, model)
    try:
        return tiktoken.encoding_for_model(target)
    except KeyError:
        try:
            return tiktoken.get_encoding("cl100k_base")
        except KeyError:
            return None


__all__ = ["TokenMeter", "TokenMeasurement"]
