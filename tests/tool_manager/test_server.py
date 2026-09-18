"""Real SDK dispatch tests: closed inputs, structured results and shared engine."""

import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
server_module = importlib.import_module("ceratops_tool_manager.server")


def test_mcp_has_exact_operations_and_rejects_unknown_inputs(monkeypatch):
    class StubEngine:
        def install(self, tool_name, version):
            return {"installed_version": version, "tool_name": tool_name}

        update = install

        def versions(self, tool_name):
            return {"tool_name": tool_name, "installed_version": "1.0.0"}

    monkeypatch.setattr(server_module, "Engine", StubEngine)
    service = server_module.build_server()

    async def exercise():
        tools = await service.list_tools()
        assert {tool.name for tool in tools} == {"install", "update", "versions"}
        assert all(tool.input_schema["additionalProperties"] is False for tool in tools)
        for name in ("install", "update"):
            response = await service.call_tool(name, {"tool_name": "fixture", "version": "1.0.0"})
            assert response.structured_content == {"installed_version": "1.0.0", "tool_name": "fixture"}
        response = await service.call_tool("versions", {})
        assert response.structured_content["tool_name"] == "ceratops_tool_manager"
        assert (await service.call_tool("versions", {"root": "C:/escape"})).is_error
        assert (await service.call_tool("create-tool", {})).is_error
        assert (await service.call_tool("package", {"source": "reviewed-source"})).is_error
        assert (await service.call_tool("install", {"tool_name": "fixture", "version": "1.0.0", "source": "."})).is_error
        assert (await service.call_tool("install", {"tool_id": "fixture", "version": "1.0.0"})).is_error

    asyncio.run(exercise())
