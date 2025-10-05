"""Helper script to run integration tests that hit the live Anthropic API."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict


def _load_dotenv(env_path: Path) -> Dict[str, str]:
    """Minimal .env loader to avoid pulling in additional dependencies."""

    values: Dict[str, str] = {}
    if not env_path.exists():
        return values

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()

    dotenv_values = _load_dotenv(repo_root / ".env")
    env.update(dotenv_values)

    api_key = env.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        print(
            "ANTHROPIC_API_KEY is required for integration tests.\n"
            "Provide it in the environment or create a .env file next to the repository root.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    command = ["pytest", "-m", "integration", "-vv"]

    completed = subprocess.run(command, cwd=str(repo_root), env=env)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


if __name__ == "__main__":
    main()
