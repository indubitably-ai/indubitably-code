"""Shared configuration helpers for Anthropic client settings."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

DEFAULT_MODEL = "claude-3-7-sonnet-latest"
DEFAULT_MAX_TOKENS = 1024


@dataclass(frozen=True)
class AnthropicConfig:
    """Simple container for Anthropic model configuration."""

    model: str
    max_tokens: int


def _parse_positive_int(raw: Optional[str], fallback: int) -> int:
    """Return a positive integer parsed from *raw*, or *fallback* on failure."""

    if raw is None:
        return fallback
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return fallback
    return value if value > 0 else fallback


def load_anthropic_config() -> AnthropicConfig:
    """Load Anthropic settings from environment variables with safe fallbacks."""

    model = (os.getenv("ANTHROPIC_MODEL") or "").strip() or DEFAULT_MODEL
    max_tokens = _parse_positive_int(os.getenv("ANTHROPIC_MAX_TOKENS"), DEFAULT_MAX_TOKENS)
    return AnthropicConfig(model=model, max_tokens=max_tokens)


__all__ = ["AnthropicConfig", "DEFAULT_MODEL", "DEFAULT_MAX_TOKENS", "load_anthropic_config"]
