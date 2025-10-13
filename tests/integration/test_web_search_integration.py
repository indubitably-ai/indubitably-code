"""Integration test for the web_search tool using stubbed network responses."""
from __future__ import annotations

import json

from agent import Tool
from agent_runner import AgentRunOptions, AgentRunner
from tests.integration.helpers import queue_tool_turn
from tests.mocking import MockAnthropic

from tools_web_search import web_search_tool_def, web_search_impl


def _build_web_search_tool() -> Tool:
    definition = web_search_tool_def()
    return Tool(
        name=definition["name"],
        description=definition["description"],
        input_schema=definition["input_schema"],
        fn=web_search_impl,
        capabilities={"network"},
    )


def test_web_search_returns_stubbed_results(monkeypatch) -> None:
    results = [
        {"title": "Example Domain", "link": "https://example.com", "snippet": "Example snippet"},
        {"title": "Docs", "link": "https://example.com/docs", "snippet": "Docs snippet"},
    ]

    monkeypatch.setattr("tools_web_search._search_duckduckgo", lambda term, limit: results)
    monkeypatch.setattr("tools_web_search._search_duckduckgo_api", lambda term, limit: [])
    monkeypatch.setattr("tools_web_search._search_bing", lambda term, limit: [])
    monkeypatch.setattr("tools_web_search._search_wikipedia", lambda term, limit: [])

    client = MockAnthropic()
    queue_tool_turn(
        client,
        tool_name="web_search",
        payloads=[{"search_term": "example domain", "max_results": 2}],
        final_text="Fetched search results.",
    )

    runner = AgentRunner(
        tools=[_build_web_search_tool()],
        options=AgentRunOptions(max_turns=1, verbose=False),
        client=client,
    )

    result = runner.run("Search for example")

    payload = json.loads(result.tool_events[0].result)
    assert payload["engine"] == "duckduckgo"
    assert len(payload["results"]) == 2
    assert payload["results"][0]["link"] == "https://example.com"
