"""Deterministic renderers for prompt payloads."""
from __future__ import annotations

from typing import Iterable, List


def render_code_block(path: str, content: str, *, lang: str = "") -> str:
    fence = f"```{lang}".rstrip()
    return f"{path}\n{fence}\n{content}\n```"


def render_diff(path: str, diff: str) -> str:
    return f"{path}\n```diff\n{diff}\n```"


def render_table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    header_items = list(headers)
    header_row = " | ".join(header_items)
    divider = " | ".join(["---"] * len(header_items))
    body = [" | ".join(list(row)) for row in rows]
    table_lines: List[str] = [header_row, divider, *body]
    return "\n".join(table_lines)


__all__ = ["render_code_block", "render_diff", "render_table"]
