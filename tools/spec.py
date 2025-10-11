"""Tool specification models."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass(slots=True)
class ToolSpec:
    """Describes a tool in the registry."""

    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)

    def to_anthropic_definition(self) -> Dict[str, Any]:
        """Return a dict compatible with Anthropic tool definitions."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


__all__ = ["ToolSpec"]
