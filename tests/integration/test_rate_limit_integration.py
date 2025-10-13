"""Integration tests for rate-limit retry handling."""
from __future__ import annotations

from agent_runner import AgentRunOptions, AgentRunner
from anthropic import RateLimitError
from types import SimpleNamespace
from tests.mocking.responses import MockAnthropicResponse, text_block


class RateLimitAnthropic:
    def __init__(self, attempts_before_success: int = 2) -> None:
        self._remaining = attempts_before_success
        self.messages = self

    def create(self, **_kwargs):
        if self._remaining > 0:
            self._remaining -= 1
            raise RateLimitError('rate limit', response=SimpleNamespace(request=SimpleNamespace(url='https://api.test'), status_code=429, text='rate limit', headers={} ), body=None)
        return MockAnthropicResponse.from_blocks([text_block("Rate limit succeeded")])


def test_rate_limit_retries_and_succeeds(monkeypatch) -> None:
    client = RateLimitAnthropic(attempts_before_success=2)

    runner = AgentRunner(
        tools=[],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
    )

    result = runner.run("Handle rate limit")

    assert "Rate limit succeeded" in result.final_response
