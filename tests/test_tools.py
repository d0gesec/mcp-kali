"""Tests for ToolRegistry and built-in tool handlers."""

from __future__ import annotations

import os
import tempfile
from typing import TYPE_CHECKING

import pytest

from src.core.registry import ToolRegistry
from src.tools.core_tools import make_execute_command_handler, handle_list_files

if TYPE_CHECKING:
    from conftest import ServerHarness

# Create a standalone handler (no background task manager needed for unit tests)
handle_execute_command = make_execute_command_handler(task_manager=None)


# ---------------------------------------------------------------------------
# ToolRegistry unit tests
# ---------------------------------------------------------------------------


class TestToolRegistry:
    """Unit tests for the ToolRegistry class."""

    def test_empty_registry(self, tool_registry: ToolRegistry):
        assert tool_registry.list_tools() == []

    def test_register_and_list(self, tool_registry: ToolRegistry):
        tool_registry.register(
            name="test_tool",
            description="A test tool",
            input_schema={"type": "object", "properties": {}},
            handler=lambda args: {"content": [{"type": "text", "text": "ok"}], "isError": False},
        )
        tools = tool_registry.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "test_tool"
        assert tools[0]["description"] == "A test tool"
        assert "inputSchema" in tools[0]

    def test_register_multiple_tools(self, tool_registry: ToolRegistry):
        for i in range(3):
            tool_registry.register(
                name=f"tool_{i}",
                description=f"Tool {i}",
                input_schema={"type": "object"},
                handler=lambda args: {"content": [], "isError": False},
            )
        assert len(tool_registry.list_tools()) == 3

    def test_call_registered_tool(self, tool_registry: ToolRegistry):
        tool_registry.register(
            name="echo",
            description="Echo",
            input_schema={"type": "object"},
            handler=lambda args: {
                "content": [{"type": "text", "text": args.get("msg", "")}],
                "isError": False,
            },
        )
        result = tool_registry.call_tool("echo", {"msg": "hello"})
        assert result["isError"] is False
        assert result["content"][0]["text"] == "hello"

    def test_call_unknown_tool(self, tool_registry: ToolRegistry):
        result = tool_registry.call_tool("nonexistent", {})
        assert result["isError"] is True
        assert "Unknown tool" in result["content"][0]["text"]

    def test_handler_exception_caught(self, tool_registry: ToolRegistry):
        def bad_handler(args):
            raise RuntimeError("boom")

        tool_registry.register(
            name="bad",
            description="Fails",
            input_schema={"type": "object"},
            handler=bad_handler,
        )
        result = tool_registry.call_tool("bad", {})
        assert result["isError"] is True
        assert "boom" in result["content"][0]["text"]

    def test_overwrite_tool(self, tool_registry: ToolRegistry):
        tool_registry.register(
            name="x", description="v1", input_schema={},
            handler=lambda a: {"content": [{"type": "text", "text": "v1"}], "isError": False},
        )
        tool_registry.register(
            name="x", description="v2", input_schema={},
            handler=lambda a: {"content": [{"type": "text", "text": "v2"}], "isError": False},
        )
        assert len(tool_registry.list_tools()) == 1
        assert tool_registry.list_tools()[0]["description"] == "v2"
        result = tool_registry.call_tool("x", {})
        assert result["content"][0]["text"] == "v2"


# ---------------------------------------------------------------------------
# handle_execute_command tests
# ---------------------------------------------------------------------------


class TestExecuteCommand:
    """Tests for the execute_command tool handler."""

    def test_simple_echo(self):
        result = handle_execute_command({"command": "echo hello"})
        assert result["isError"] is False
        assert "hello" in result["content"][0]["text"]

    def test_command_exit_code(self):
        result = handle_execute_command({"command": "exit 42"})
        assert "exit_code: 42" in result["content"][0]["text"]

    def test_stderr_captured(self):
        result = handle_execute_command({"command": "echo oops >&2"})
        text = result["content"][0]["text"]
        assert "oops" in text

    def test_missing_command_param(self):
        result = handle_execute_command({})
        assert result["isError"] is True
        assert "Missing" in result["content"][0]["text"]

    def test_command_not_string(self):
        result = handle_execute_command({"command": 123})
        assert result["isError"] is True

    def test_empty_command_string(self):
        result = handle_execute_command({"command": ""})
        assert result["isError"] is True

    def test_timeout_parameter(self):
        # Short timeout on a sleep command
        result = handle_execute_command({"command": "sleep 10", "timeout": 1})
        text = result["content"][0]["text"]
        assert "timed out" in text.lower()

    def test_invalid_timeout_uses_default(self):
        # Negative timeout should fall back to default (won't actually timeout)
        result = handle_execute_command({"command": "echo ok", "timeout": -5})
        assert result["isError"] is False
        assert "ok" in result["content"][0]["text"]

    def test_multiline_output(self):
        result = handle_execute_command({"command": "printf 'line1\\nline2\\nline3'"})
        text = result["content"][0]["text"]
        assert "line1" in text
        assert "line2" in text
        assert "line3" in text


# ---------------------------------------------------------------------------
# handle_list_files tests
# ---------------------------------------------------------------------------


class TestListFiles:
    """Tests for the list_files tool handler."""

    def test_list_root(self):
        result = handle_list_files({"path": "/"})
        assert result["isError"] is False
        text = result["content"][0]["text"]
        # Root should have some entries
        assert len(text.strip().split("\n")) > 0

    def test_list_nonexistent_directory(self):
        result = handle_list_files({"path": "/nonexistent_dir_abc123"})
        assert result["isError"] is True
        assert "Not a directory" in result["content"][0]["text"]

    def test_list_with_tempdir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create some files
            for name in ["a.txt", "b.txt", "c.txt"]:
                open(os.path.join(tmpdir, name), "w").close()
            os.mkdir(os.path.join(tmpdir, "subdir"))

            result = handle_list_files({"path": tmpdir})
            assert result["isError"] is False
            text = result["content"][0]["text"]
            assert "a.txt" in text
            assert "b.txt" in text
            assert "c.txt" in text
            assert "subdir/" in text

    def test_list_recursive(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "sub", "deep"))
            open(os.path.join(tmpdir, "top.txt"), "w").close()
            open(os.path.join(tmpdir, "sub", "mid.txt"), "w").close()
            open(os.path.join(tmpdir, "sub", "deep", "bot.txt"), "w").close()

            result = handle_list_files({"path": tmpdir, "recursive": True})
            assert result["isError"] is False
            text = result["content"][0]["text"]
            assert "top.txt" in text
            assert "mid.txt" in text
            assert "bot.txt" in text

    def test_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_list_files({"path": tmpdir})
            assert result["isError"] is False
            assert "(empty directory)" in result["content"][0]["text"]

    def test_default_path_fallback(self):
        # When path is not a string, should fall back to /workspace or CWD
        result = handle_list_files({"path": 123})
        # May or may not error depending on whether /workspace exists,
        # but should not crash
        assert "content" in result

    def test_directories_have_trailing_slash(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            os.mkdir(os.path.join(tmpdir, "mydir"))
            open(os.path.join(tmpdir, "myfile"), "w").close()

            result = handle_list_files({"path": tmpdir})
            text = result["content"][0]["text"]
            assert "mydir/" in text
            # file should NOT have trailing slash
            lines = text.strip().split("\n")
            file_line = [l for l in lines if "myfile" in l][0]
            assert not file_line.endswith("/")


# ---------------------------------------------------------------------------
# MCP protocol tools/call tests via ServerHarness
# ---------------------------------------------------------------------------


class TestToolsCallProtocol:
    """Test tools/call through the full JSON-RPC flow."""

    def test_call_execute_command(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "execute_command", "arguments": {"command": "echo test"}},
        })
        assert resp is not None
        assert "result" in resp
        assert resp["result"]["isError"] is False

    def test_call_missing_tool_name(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"arguments": {"command": "echo test"}},
        })
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32602  # INVALID_PARAMS

    def test_call_unknown_tool_name(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        })
        assert resp is not None
        # Unknown tool returns success envelope with isError=True content
        assert "result" in resp
        assert resp["result"]["isError"] is True

    def test_call_with_no_arguments(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "list_files"},
        })
        assert resp is not None
        # Should use default arguments
        assert "result" in resp

    def test_tools_list(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })
        assert resp is not None
        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "execute_command" in names
        assert "list_files" in names
        # Each tool has the required fields
        for t in tools:
            assert "name" in t
            assert "description" in t
            assert "inputSchema" in t
