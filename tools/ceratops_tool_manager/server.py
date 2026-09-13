"""Local stdio MCP with exactly three tools and no creation/execution endpoint."""

import json
from typing import Any

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .engine import Engine


class DeploymentServer(MCPServer):
    """Reject unknown inputs before SDK conversion can ignore extra fields."""

    async def list_tools(self):
        tools = await super().list_tools()
        for tool in tools:
            tool.input_schema["additionalProperties"] = False
        return tools

    async def call_tool(self, name, arguments, context=None):
        expected = {"versions": {"tool_id"}, "install": {"tool_id", "version"}, "update": {"tool_id", "version"}}
        if name not in expected or set(arguments) - expected[name]:
            return CallToolResult(is_error=True, content=[TextContent(type="text", text="Unknown operation or argument.")])
        return await super().call_tool(name, arguments, context)


def result(value: dict[str, Any]) -> CallToolResult:
    return CallToolResult(structured_content=value, content=[TextContent(type="text", text=json.dumps(value))])


def build_server() -> MCPServer:
    server = DeploymentServer("Ceratops Tool Manager")
    engine = Engine()

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
    def install(tool_id: str, version: str) -> CallToolResult:
        """Install an exact registered release, including a selected previous version."""
        return result(engine.install(tool_id, version))

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=False))
    def update(tool_id: str, version: str) -> CallToolResult:
        """Update an installed tool to an exact registered release; reconnect after a self-update."""
        return result(engine.update(tool_id, version))

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False))
    def versions(tool_id: str = "ceratops_tool_manager") -> CallToolResult:
        """Inspect installed, available, and this manager process's running versions."""
        return result(engine.versions(tool_id))

    return server
