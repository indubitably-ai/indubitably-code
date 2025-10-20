from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

from pydantic import ValidationError

from tools.handler import ToolOutput
from tools.output import ExecOutput, format_exec_output
from tools.schemas import RunTerminalCmdInput


_DEF_SHELL = os.environ.get("SHELL") or "/bin/zsh"
_LOG_DIR = Path("run_logs")


def run_terminal_cmd_tool_def() -> dict:
    return {
        "name": "run_terminal_cmd",
        "description": (
            "Execute shell commands on the host in either foreground or background mode with rich metadata capture. Provide `command` as a full shell string and set `is_background` to false for synchronous execution (capturing stdout/stderr) or true to dispatch the process with log files under run_logs/. "
            "Optional fields include `explanation` (helpful audit note), `cwd` to change directories, `env` to override environment variables, `timeout` for foreground watchdogs, `stdin` to stream input, and `shell` to select the interpreter (defaults to $SHELL). Foreground executions automatically disable pagers when possible and wrap results in ExecOutput JSON summarizing exit code, duration, and combined output. "
            "Example: to run tests non-interactively, call run_terminal_cmd with command='pytest -q', is_background=false, timeout=600. Avoid using this tool for interactive sessions, destructive operations without human approval, or long-running daemons unless you intentionally choose background mode and monitor the generated logs."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "command": {"type": "string", "description": "The exact shell command to execute."},
                "is_background": {"type": "boolean", "description": "Run the command detached in the background."},
                "explanation": {"type": "string", "description": "One sentence on why this command is being run."},
                "cwd": {"type": "string", "description": "Optional working directory for the command."},
                "env": {
                    "type": "object",
                    "description": "Optional environment variable overrides.",
                    "additionalProperties": {"type": "string"},
                },
                "timeout": {
                    "type": "number",
                    "minimum": 0,
                    "description": "Optional timeout in seconds for foreground commands.",
                },
                "stdin": {
                    "type": "string",
                    "description": "Optional stdin content to pass to the command (foreground only).",
                },
                "shell": {
                    "type": "string",
                    "description": "Override shell executable (defaults to $SHELL or /bin/zsh).",
                },
            },
            "required": ["command", "is_background"],
        },
    }


def _ensure_log_dir() -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)


def _merge_env(overrides: Optional[Dict[str, str]]) -> Dict[str, str]:
    if not overrides:
        return {**os.environ}
    merged: Dict[str, str] = {**os.environ}
    for key, value in overrides.items():
        merged[str(key)] = str(value)
    return merged


def _supports_pipefail(shell_path: str) -> bool:
    basename = os.path.basename(shell_path)
    return basename in {"bash", "zsh"}


def _run_foreground(
    command: str,
    *,
    cwd: Optional[str],
    env: Optional[Dict[str, str]],
    shell_executable: str,
    timeout: Optional[float],
    stdin_data: Optional[str],
) -> ExecOutput:
    # Best-effort to avoid paging: append '| cat' if command likely to use a pager and not already piped
    likely_pages = ["git log", "man ", "less", "more "]
    if not any(tok in command for tok in ["|", ">", "2>"]) and any(p in command for p in likely_pages):
        command = f"{command} | cat"

    env_map = _merge_env(env)
    env_map.setdefault("TERM", "xterm-256color")

    start = time.time()
    try:
        completed = subprocess.run(
            command,
            shell=True,
            executable=shell_executable,
            capture_output=True,
            text=True,
            env=env_map,
            cwd=cwd or None,
            timeout=timeout,
            input=stdin_data,
        )
        duration = time.time() - start
        return ExecOutput(
            exit_code=completed.returncode,
            duration_seconds=duration,
            output=(completed.stdout or "") + (completed.stderr or ""),
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.time() - start
        return ExecOutput(
            exit_code=-1,
            duration_seconds=duration,
            output=(exc.stdout or "") + (exc.stderr or ""),
            timed_out=True,
        )


def _run_background(
    command: str,
    *,
    cwd: Optional[str],
    env: Optional[Dict[str, str]],
    shell_executable: str,
) -> ExecOutput:
    _ensure_log_dir()
    ts = time.strftime("%Y%m%d-%H%M%S")
    job_id = f"job-{ts}-{uuid.uuid4().hex[:8]}"

    stdout_path = _LOG_DIR / f"{job_id}.out.log"
    stderr_path = _LOG_DIR / f"{job_id}.err.log"

    stdout_f = open(stdout_path, "w", encoding="utf-8")
    stderr_f = open(stderr_path, "w", encoding="utf-8")

    wrapped_cmd = command
    if _supports_pipefail(shell_executable):
        wrapped_cmd = f"set -o pipefail; {command}"

    env_map = _merge_env(env)
    env_map.setdefault("TERM", "xterm-256color")

    proc = subprocess.Popen(
        wrapped_cmd,
        shell=True,
        executable=shell_executable,
        stdout=stdout_f,
        stderr=stderr_f,
        preexec_fn=os.setsid if hasattr(os, "setsid") else None,
        env=env_map,
        cwd=cwd or None,
    )

    summary_lines = [
        "background command dispatched",
        f"job_id: {job_id}",
        f"pid: {proc.pid}",
        f"stdout_log: {stdout_path}",
        f"stderr_log: {stderr_path}",
        "hint: tail -f <log-path>",
    ]
    return ExecOutput(
        exit_code=0,
        duration_seconds=0.0,
        output="\n".join(summary_lines) + "\n",
        timed_out=False,
    )


def run_terminal_cmd_impl(input: Dict[str, Any]) -> ToolOutput:
    try:
        params = RunTerminalCmdInput(**input)
    except ValidationError as exc:
        messages = []
        for err in exc.errors():
            loc = ".".join(str(part) for part in err.get("loc", ())) or "input"
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        raise ValueError("; ".join(messages)) from exc

    command = params.command.strip()
    if not command:
        raise ValueError("command must contain text")

    is_background = params.is_background
    cwd = (params.cwd or "").strip() or None
    env_overrides = {str(k): str(v) for k, v in (params.env or {}).items()}

    shell_override = (params.shell or "").strip() or None
    shell_executable = shell_override or _DEF_SHELL

    timeout_val = params.timeout
    stdin_data = params.stdin
    if stdin_data is not None:
        stdin_data = str(stdin_data)

    # Basic guardrails: discourage obviously interactive programs in foreground
    interactive_bins = {"vim", "nano", "top", "htop", "less", "more"}
    if not is_background:
        try:
            first_bin = shlex.split(command)[0]
            base = os.path.basename(first_bin)
            if base in interactive_bins:
                return ToolOutput(
                    content=json.dumps({
                        "ok": False,
                        "error": f"Refusing to run interactive program '{base}' in foreground; set is_background=true or choose a non-interactive flag.",
                    }),
                    success=False,
                )
        except Exception:
            pass

    if is_background:
        exec_output = _run_background(
            command,
            cwd=cwd,
            env=env_overrides,
            shell_executable=shell_executable,
        )
    else:
        exec_output = _run_foreground(
            command,
            cwd=cwd,
            env=env_overrides,
            shell_executable=shell_executable,
            timeout=timeout_val,
            stdin_data=stdin_data,
        )

    formatted = format_exec_output(exec_output)
    metadata: Dict[str, Any] = {}
    if exec_output.truncated:
        metadata["truncated"] = True
    if exec_output.timed_out:
        metadata["timed_out"] = True
    return ToolOutput(
        content=formatted,
        success=True,
        metadata=metadata or None,
    )
