"""Command-line interface for running the Anthropic agent headlessly."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from agent_runner import AgentRunOptions, AgentRunResult, AgentRunner
from runner_config import RunnerConfig, load_runner_config
from run import build_default_tools


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Indubitably agent in headless mode")
    prompt_group = parser.add_mutually_exclusive_group(required=False)
    prompt_group.add_argument("--prompt", help="User prompt to start the session with")
    prompt_group.add_argument("--prompt-file", type=Path, help="File containing the initial prompt")

    parser.add_argument("--config", type=Path, help="Path to TOML config file with runner defaults")
    parser.add_argument("--max-turns", type=int, default=None, help="Maximum Anthropic response turns to allow")

    exit_group = parser.add_mutually_exclusive_group()
    exit_group.add_argument(
        "--exit-on-tool-error",
        dest="exit_on_tool_error",
        action="store_const",
        const=True,
        help="Stop immediately if a tool returns an error",
    )
    exit_group.add_argument(
        "--no-exit-on-tool-error",
        dest="exit_on_tool_error",
        action="store_const",
        const=False,
        help="Continue running even if tools fail (default)",
    )
    parser.set_defaults(exit_on_tool_error=None)

    parser.add_argument("--allowed-tools", help="Comma-separated list of tool names to allow (defaults to all)")
    parser.add_argument("--blocked-tools", help="Comma-separated list of tool names to block")

    dry_group = parser.add_mutually_exclusive_group()
    dry_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_const",
        const=True,
        help="Do not execute tools; report planned calls",
    )
    dry_group.add_argument(
        "--no-dry-run",
        dest="dry_run",
        action="store_const",
        const=False,
        help="Execute tools normally (default)",
    )
    parser.set_defaults(dry_run=None)

    parser.add_argument("--audit-log", type=Path, help="Write JSONL audit log of tool invocations to this path")
    parser.add_argument(
        "--changes-log",
        type=Path,
        help="Write JSONL log of file write operations to this path",
    )
    debug_group = parser.add_mutually_exclusive_group()
    debug_group.add_argument(
        "--debug-tool-use",
        dest="debug_tool_use",
        action="store_const",
        const=True,
        help="Print detailed tool invocation information and enable command logging",
    )
    debug_group.add_argument(
        "--no-debug-tool-use",
        dest="debug_tool_use",
        action="store_const",
        const=False,
        help="Disable detailed tool invocation logging (default)",
    )
    parser.set_defaults(debug_tool_use=None)
    parser.add_argument(
        "--tool-debug-log",
        type=Path,
        help="When tool debugging is enabled, append JSONL records of tool invocations to this path",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary")
    parser.add_argument("--verbose", action="store_true", help="Print detailed progress information")

    return parser.parse_args(argv)


def load_prompt(args: argparse.Namespace) -> str:
    if args.prompt_file:
        return args.prompt_file.read_text(encoding="utf-8")
    if args.prompt:
        return args.prompt
    if not sys.stdin.isatty():
        return sys.stdin.read()
    raise SystemExit("No prompt provided. Use --prompt, --prompt-file, or pipe input via stdin.")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    prompt = load_prompt(args)

    config_data = _load_runner_config(args.config)

    allowed_override = _parse_name_set(args.allowed_tools)
    blocked_override = _parse_name_set(args.blocked_tools)

    options = AgentRunOptions(
        max_turns=_coalesce_int(args.max_turns, config_data.max_turns, fallback=8),
        exit_on_tool_error=_coalesce_bool(args.exit_on_tool_error, config_data.exit_on_tool_error, fallback=False),
        allowed_tools=allowed_override if allowed_override is not None else config_data.allowed_tools,
        blocked_tools=(blocked_override if blocked_override is not None else (config_data.blocked_tools or set())) or set(),
        dry_run=_coalesce_bool(args.dry_run, config_data.dry_run, fallback=False),
        audit_log_path=args.audit_log or config_data.audit_log_path,
        changes_log_path=args.changes_log or config_data.changes_log_path,
        verbose=args.verbose,
        debug_tool_use=_coalesce_bool(args.debug_tool_use, config_data.debug_tool_use, fallback=False),
        tool_debug_log_path=args.tool_debug_log or config_data.tool_debug_log_path,
    )

    tools = build_default_tools()
    runner = AgentRunner(tools, options)

    if args.verbose:
        print(f"Running headless agent with {len(runner.active_tools)} tools...", file=sys.stderr)

    result = runner.run(prompt)

    if args.json:
        print(_result_to_json(result))
    else:
        _print_human_summary(result)

    if args.verbose:
        print(f"Stopped after {result.turns_used} turns: {result.stopped_reason}", file=sys.stderr)

    return 0


def _parse_name_set(raw: Optional[str]) -> Optional[set[str]]:
    if not raw:
        return None
    names = {name.strip() for name in raw.split(",") if name.strip()}
    return names or None


def _coalesce_int(*values, fallback: int) -> int:
    for value in values:
        if value is not None:
            return int(value)
    return fallback


def _coalesce_bool(*values, fallback: bool) -> bool:
    for value in values:
        if value is not None:
            return bool(value)
    return fallback


def _load_runner_config(config_path: Optional[Path]) -> RunnerConfig:
    if not config_path:
        return RunnerConfig()
    try:
        return load_runner_config(config_path)
    except Exception as exc:  # pragma: no cover - surfaced to user
        raise SystemExit(f"Failed to load config {config_path}: {exc}")


def _result_to_json(result: AgentRunResult) -> str:
    payload: Dict[str, Any] = {
        "final_response": result.final_response,
        "stopped_reason": result.stopped_reason,
        "turns_used": result.turns_used,
        "edited_files": result.edited_files,
        "tools": [event.to_dict() for event in result.tool_events],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _print_human_summary(result: AgentRunResult) -> None:
    final = result.final_response or "<no final response>"
    print(final)
    print("\n---")
    print(f"Stopped reason: {result.stopped_reason} (turns: {result.turns_used})")

    if result.tool_events:
        print("Tools executed:")
        for event in result.tool_events:
            status = "error" if event.is_error else "ok"
            if event.skipped:
                status = "skipped"
            paths = f" paths={event.paths}" if event.paths else ""
            print(f"  - turn {event.turn}: {event.tool_name} [{status}]{paths}")
    else:
        print("Tools executed: none")

    if result.edited_files:
        print("Edited files:")
        for path in result.edited_files:
            print(f"  - {path}")
    else:
        print("Edited files: none")


if __name__ == "__main__":
    raise SystemExit(main())
