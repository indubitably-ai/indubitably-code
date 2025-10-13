"""Utilities for constructing isolated agent runners in tests."""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Sequence

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from session import SessionSettings, load_session_settings
from tests.mocking import MockAnthropic


@dataclass
class TestAgent:
    """Container for an agent runner operating in an isolated environment."""

    home_dir: tempfile.TemporaryDirectory[str]
    work_dir: tempfile.TemporaryDirectory[str]
    runner: AgentRunner
    client: Any
    tools: Sequence[Tool]
    options: AgentRunOptions
    session_settings: SessionSettings
    _original_home: Optional[str]

    def run_turn(self, prompt: str, *, initial_conversation: Optional[Sequence[dict]] = None):
        """Execute a single agent turn and return the result."""
        return self.runner.run(prompt, initial_conversation=initial_conversation)

    def work_path(self, relative: str | Path) -> Path:
        """Return an absolute path within the test work directory."""
        return Path(self.work_dir.name) / Path(relative)

    def home_path(self, relative: str | Path) -> Path:
        """Return an absolute path within the test home directory."""
        return Path(self.home_dir.name) / Path(relative)

    def cleanup(self) -> None:
        """Restore mutated state and remove temporary resources."""
        if self._original_home is not None:
            os.environ["HOME"] = self._original_home
        else:
            os.environ.pop("HOME", None)
        self.home_dir.cleanup()
        self.work_dir.cleanup()


TestAgent.__test__ = False


class TestAgentBuilder:
    """Builder that assembles ``TestAgent`` instances for unit tests."""

    def __init__(self) -> None:
        self._tools: List[Tool] = []
        self._options_mutators: List[Callable[[AgentRunOptions], None]] = []
        self._session_settings: Optional[SessionSettings] = None
        self._client: Optional[Any] = None

    def with_tools(self, tools: Iterable[Tool]) -> "TestAgentBuilder":
        """Add a collection of tools to the agent."""
        self._tools.extend(tools)
        return self

    def add_tool(self, tool: Tool) -> "TestAgentBuilder":
        """Add a single tool to the agent."""
        self._tools.append(tool)
        return self

    def with_options(self, mutator: Callable[[AgentRunOptions], None]) -> "TestAgentBuilder":
        """Apply a mutation to the default ``AgentRunOptions`` instance."""
        self._options_mutators.append(mutator)
        return self

    def with_session_settings(self, settings: SessionSettings) -> "TestAgentBuilder":
        """Use the provided session settings instead of loading defaults."""
        self._session_settings = settings
        return self

    def with_client(self, client: Any) -> "TestAgentBuilder":
        """Provide a pre-configured Anthropic mock client."""
        self._client = client
        return self

    def build(self) -> TestAgent:
        """Construct a ``TestAgent`` with isolated temp directories."""
        home_dir = tempfile.TemporaryDirectory(prefix="agent-home-")
        work_dir = tempfile.TemporaryDirectory(prefix="agent-work-")

        original_home = os.environ.get("HOME")
        os.environ["HOME"] = home_dir.name

        client = self._client or MockAnthropic()

        options = AgentRunOptions()
        options.audit_log_path = Path(work_dir.name) / "audit.log"
        options.changes_log_path = Path(work_dir.name) / "changes.log"
        for mutate in self._options_mutators:
            mutate(options)

        session_settings = self._session_settings or load_session_settings()

        runner = AgentRunner(
            tools=list(self._tools),
            options=options,
            client=client,
            session_settings=session_settings,
        )

        return TestAgent(
            home_dir=home_dir,
            work_dir=work_dir,
            runner=runner,
            client=client,
            tools=tuple(self._tools),
            options=options,
            session_settings=session_settings,
            _original_home=original_home,
        )


def test_agent() -> TestAgentBuilder:
    """Convenience helper mirroring the codex-rs builder pattern."""
    return TestAgentBuilder()


TestAgentBuilder.__test__ = False
test_agent.__test__ = False
