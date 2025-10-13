import asyncio
from types import SimpleNamespace

import pytest

from tools.mcp_integration import MCPToolDiscovery, MCPServerConfig
from tools.spec import ToolSpec


class FakeTool:
    def __init__(self, name: str, description: str, schema):
        self.name = name
        self.description = description
        self.input_schema = schema


class FakeClient:
    def __init__(self, tools):
        self._tools = tools

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)


def test_discover_tools_returns_specs():
    async def factory(config: MCPServerConfig):
        assert config.name == "sample"
        tool = FakeTool("tool", "desc", {"properties": {"value": {"type": "integer"}}})
        return FakeClient([tool])

    discovery = MCPToolDiscovery(client_factory=factory)
    discovery.register_server("sample", "cmd", ["--flag"], env={"X": "1"})

    specs = asyncio.run(discovery.discover_tools("sample"))
    assert "sample/tool" in specs
    spec = specs["sample/tool"]
    assert isinstance(spec, ToolSpec)
    assert spec.description == "desc"
    assert spec.input_schema["properties"]["value"]["type"] == "number"


def test_discover_unknown_server_raises():
    discovery = MCPToolDiscovery()
    with pytest.raises(ValueError):
        asyncio.run(discovery.discover_tools("missing"))


def test_sanitize_schema_handles_missing_fields():
    discovery = MCPToolDiscovery()
    schema = {
        "properties": {
            "items": {
                "type": "integer",
            }
        },
        "items": {
            "properties": {
                "child": {}
            }
        },
    }
    sanitized = discovery._sanitize_json_schema(schema)
    assert sanitized["type"] == "object"
    assert sanitized["properties"]["items"]["type"] == "number"
    assert sanitized["items"].get("type") == "object"
    assert sanitized["items"]["properties"]["child"]["type"] == "string"


def test_factory_not_provided_raises_not_implemented():
    discovery = MCPToolDiscovery()
    discovery.register_server("sample", "cmd", [])
    with pytest.raises(NotImplementedError):
        asyncio.run(discovery.discover_tools("sample"))
