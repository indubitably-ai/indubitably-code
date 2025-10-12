"""MCP server discovery utilities."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from tools.spec import ToolSpec


@dataclass
class MCPServerConfig:
    """Configuration for connecting to an MCP server."""

    name: str
    command: str
    args: List[str]
    env: Dict[str, str]


class MCPToolDiscovery:
    """Discovers MCP-provided tools and converts schemas for local use."""

    def __init__(
        self,
        client_factory: Optional[Callable[[MCPServerConfig], Awaitable[Any]]] = None,
    ) -> None:
        self.servers: Dict[str, MCPServerConfig] = {}
        self._client_factory = client_factory

    def register_server(
        self,
        name: str,
        command: str,
        args: List[str],
        env: Optional[Dict[str, str]] = None,
    ) -> None:
        """Register an MCP server configuration for later discovery."""
        self.servers[name] = MCPServerConfig(
            name=name,
            command=command,
            args=list(args),
            env=dict(env or {}),
        )

    async def discover_tools(self, server_name: str) -> Dict[str, ToolSpec]:
        """Connect to the configured server and return discovered ToolSpecs."""
        if server_name not in self.servers:
            raise ValueError(f"Unknown MCP server: {server_name}")

        config = self.servers[server_name]
        client = await self._connect_mcp_server(config)

        response = await client.list_tools()
        result: Dict[str, ToolSpec] = {}
        for tool in getattr(response, "tools", []):
            fq_name = f"{server_name}/{tool.name}"
            spec = self._convert_mcp_tool_to_spec(fq_name, tool)
            result[fq_name] = spec
        return result

    async def _connect_mcp_server(self, config: MCPServerConfig) -> Any:
        if self._client_factory is None:
            raise NotImplementedError("MCP client integration not implemented")
        return await self._client_factory(config)

    def _convert_mcp_tool_to_spec(self, fq_name: str, mcp_tool: Any) -> ToolSpec:
        schema = getattr(mcp_tool, "input_schema", {}) or {}
        sanitized = self._sanitize_json_schema(dict(schema))
        description = getattr(mcp_tool, "description", "") or ""
        return ToolSpec(name=fq_name, description=description, input_schema=sanitized)

    def _sanitize_json_schema(self, schema: Any) -> Any:
        if not isinstance(schema, dict):
            return schema

        schema_type = schema.get("type")
        if schema_type is None:
            if "properties" in schema or "additionalProperties" in schema:
                schema_type = "object"
            elif "items" in schema:
                schema_type = "array"
            elif "enum" in schema or "const" in schema:
                schema_type = "string"
            elif any(key in schema for key in ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum")):
                schema_type = "number"
            else:
                schema_type = "string"
            schema["type"] = schema_type

        if schema_type == "integer":
            schema["type"] = "number"
            schema_type = "number"

        if schema_type == "object":
            schema.setdefault("properties", {})
            for key, value in list(schema["properties"].items()):
                schema["properties"][key] = self._sanitize_json_schema(value)
            additional = schema.get("additionalProperties")
            if isinstance(additional, dict):
                schema["additionalProperties"] = self._sanitize_json_schema(additional)

        if schema_type == "array":
            schema.setdefault("items", {"type": "string"})

        if "items" in schema:
            schema["items"] = self._sanitize_json_schema(schema["items"])

        return schema


__all__ = ["MCPToolDiscovery", "MCPServerConfig"]
