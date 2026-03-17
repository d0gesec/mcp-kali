"""Tests for enhanced ToolRegistry: dynamic registration, metadata, history, search."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.core.registry import ToolRegistry
from src.tools.base import create_generic_tool_handler
from src.utils.validation import validate_package_name, validate_tool_definition

if TYPE_CHECKING:
    from conftest import ServerHarness


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class TestValidatePackageName:

    def test_valid_names(self):
        assert validate_package_name("nmap") is None
        assert validate_package_name("python3-pip") is None
        assert validate_package_name("lib32z1") is None
        assert validate_package_name("g++") is None

    def test_empty(self):
        assert validate_package_name("") is not None

    def test_not_string(self):
        assert validate_package_name(123) is not None  # type: ignore[arg-type]

    def test_too_long(self):
        assert validate_package_name("a" * 200) is not None

    def test_invalid_chars(self):
        assert validate_package_name("nmap; rm -rf /") is not None
        assert validate_package_name("$(whoami)") is not None
        assert validate_package_name("pkg name") is not None

    def test_starts_with_special(self):
        assert validate_package_name("-nmap") is not None
        assert validate_package_name(".nmap") is not None


class TestValidateToolDefinition:

    def test_valid(self):
        assert validate_tool_definition("my-tool", "does stuff", {"type": "object"}) is None

    def test_empty_name(self):
        assert validate_tool_definition("", "desc", {}) is not None

    def test_bad_name_chars(self):
        assert validate_tool_definition("my tool", "desc", {}) is not None
        assert validate_tool_definition("tool;rm", "desc", {}) is not None

    def test_empty_description(self):
        assert validate_tool_definition("tool", "", {}) is not None

    def test_schema_not_dict(self):
        assert validate_tool_definition("tool", "desc", "not a dict") is not None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dynamic registration
# ---------------------------------------------------------------------------


class TestDynamicRegistration:

    def test_add_tool(self, tool_registry: ToolRegistry):
        result = tool_registry.add_tool(
            name="mytool",
            description="My tool",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [{"type": "text", "text": "ok"}], "isError": False},
        )
        assert result["success"] is True
        assert len(tool_registry.list_tools()) == 1

    def test_add_tool_invalid_name(self, tool_registry: ToolRegistry):
        result = tool_registry.add_tool(
            name="bad name!",
            description="desc",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        assert result["success"] is False
        assert "Invalid tool name" in result["error"]

    def test_add_tool_empty_description(self, tool_registry: ToolRegistry):
        result = tool_registry.add_tool(
            name="tool",
            description="",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        assert result["success"] is False

    def test_remove_tool(self, tool_registry: ToolRegistry):
        tool_registry.add_tool(
            name="removeme",
            description="Will be removed",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        assert len(tool_registry.list_tools()) == 1
        result = tool_registry.remove_tool("removeme")
        assert result["success"] is True
        assert len(tool_registry.list_tools()) == 0

    def test_remove_nonexistent(self, tool_registry: ToolRegistry):
        result = tool_registry.remove_tool("ghost")
        assert result["success"] is False

    def test_update_tool_description(self, tool_registry: ToolRegistry):
        tool_registry.add_tool(
            name="updatable",
            description="old desc",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        result = tool_registry.update_tool("updatable", description="new desc")
        assert result["success"] is True
        info = tool_registry.get_tool_info("updatable")
        assert info["description"] == "new desc"

    def test_update_nonexistent(self, tool_registry: ToolRegistry):
        result = tool_registry.update_tool("ghost", description="x")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class TestMetadata:

    def test_metadata_set_on_register(self, tool_registry: ToolRegistry):
        tool_registry.add_tool(
            name="meta-test",
            description="Test metadata",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
            category="recon",
            tool_type="stateless",
            install_method="apt",
        )
        info = tool_registry.get_tool_info("meta-test")
        assert info is not None
        meta = info["metadata"]
        assert meta["category"] == "recon"
        assert meta["type"] == "stateless"
        assert meta["install_method"] == "apt"
        assert meta["usage_count"] == 0
        assert meta["last_used"] is None
        assert "registered_at" in meta

    def test_get_tool_info_nonexistent(self, tool_registry: ToolRegistry):
        assert tool_registry.get_tool_info("nope") is None

    def test_metadata_preserved_on_reregister(self, tool_registry: ToolRegistry):
        handler = lambda a: {"content": [{"type": "text", "text": "v1"}], "isError": False}
        tool_registry.add_tool(
            name="reregistered",
            description="first",
            input_schema={"type": "object"},
            handler=handler,
        )
        # Execute once to set usage_count
        tool_registry.call_tool("reregistered", {})
        info = tool_registry.get_tool_info("reregistered")
        assert info["metadata"]["usage_count"] == 1

        # Re-register — usage_count should be preserved
        tool_registry.register(
            name="reregistered",
            description="second",
            input_schema={"type": "object"},
            handler=handler,
        )
        info = tool_registry.get_tool_info("reregistered")
        assert info["metadata"]["usage_count"] == 1
        assert info["description"] == "second"


# ---------------------------------------------------------------------------
# Search & categories
# ---------------------------------------------------------------------------


class TestSearchAndCategories:

    @pytest.fixture(autouse=True)
    def _populate(self, tool_registry: ToolRegistry):
        handler = lambda a: {"content": [], "isError": False}
        tool_registry.add_tool("nmap", "Network scanner", {"type": "object"}, handler, category="recon")
        tool_registry.add_tool("sqlmap", "SQL injection tool", {"type": "object"}, handler, category="web")
        tool_registry.add_tool("gobuster", "Directory brute-forcer", {"type": "object"}, handler, category="web")
        tool_registry.add_tool("john", "Password cracker", {"type": "object"}, handler, category="crypto")

    def test_search_by_query(self, tool_registry: ToolRegistry):
        results = tool_registry.search_tools(query="sql")
        assert len(results) == 1
        assert results[0]["name"] == "sqlmap"

    def test_search_by_description(self, tool_registry: ToolRegistry):
        results = tool_registry.search_tools(query="scanner")
        assert len(results) == 1
        assert results[0]["name"] == "nmap"

    def test_search_by_category(self, tool_registry: ToolRegistry):
        results = tool_registry.search_tools(category="web")
        assert len(results) == 2
        names = {r["name"] for r in results}
        assert names == {"sqlmap", "gobuster"}

    def test_search_combined(self, tool_registry: ToolRegistry):
        results = tool_registry.search_tools(query="brute", category="web")
        assert len(results) == 1
        assert results[0]["name"] == "gobuster"

    def test_search_no_results(self, tool_registry: ToolRegistry):
        results = tool_registry.search_tools(query="nonexistent")
        assert results == []

    def test_get_tool_categories(self, tool_registry: ToolRegistry):
        cats = tool_registry.get_tool_categories()
        assert cats == {"recon": 1, "web": 2, "crypto": 1}


# ---------------------------------------------------------------------------
# Execution history
# ---------------------------------------------------------------------------


class TestExecutionHistory:

    def test_history_recorded(self, tool_registry: ToolRegistry):
        tool_registry.add_tool(
            name="hist-test",
            description="test history",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [{"type": "text", "text": "ok"}], "isError": False},
        )
        tool_registry.call_tool("hist-test", {"arg": "value"})
        history = tool_registry.get_tool_history("hist-test")
        assert len(history) == 1
        assert history[0]["arguments"] == {"arg": "value"}
        assert history[0]["is_error"] is False
        assert "duration_seconds" in history[0]
        assert "timestamp" in history[0]
        assert history[0]["output_size"] == 2  # "ok"

    def test_history_tracks_errors(self, tool_registry: ToolRegistry):
        def fail(a):
            raise RuntimeError("boom")

        tool_registry.add_tool(
            name="fail-tool",
            description="always fails",
            input_schema={"type": "object"},
            handler=fail,
        )
        tool_registry.call_tool("fail-tool", {})
        history = tool_registry.get_tool_history("fail-tool")
        assert len(history) == 1
        assert history[0]["is_error"] is True

    def test_history_limit(self, tool_registry: ToolRegistry):
        tool_registry.add_tool(
            name="limit-test",
            description="test limit",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [{"type": "text", "text": "x"}], "isError": False},
        )
        for _ in range(60):
            tool_registry.call_tool("limit-test", {})
        history = tool_registry.get_tool_history("limit-test", limit=100)
        assert len(history) == 50  # capped at 50

    def test_history_default_limit(self, tool_registry: ToolRegistry):
        tool_registry.add_tool(
            name="default-limit",
            description="test",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [{"type": "text", "text": "x"}], "isError": False},
        )
        for _ in range(20):
            tool_registry.call_tool("default-limit", {})
        history = tool_registry.get_tool_history("default-limit")
        assert len(history) == 10  # default limit=10

    def test_usage_count_increments(self, tool_registry: ToolRegistry):
        tool_registry.add_tool(
            name="counter",
            description="count calls",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        for _ in range(5):
            tool_registry.call_tool("counter", {})
        info = tool_registry.get_tool_info("counter")
        assert info["metadata"]["usage_count"] == 5
        assert info["metadata"]["last_used"] is not None

    def test_empty_history(self, tool_registry: ToolRegistry):
        assert tool_registry.get_tool_history("nonexistent") == []


# ---------------------------------------------------------------------------
# Notification callback
# ---------------------------------------------------------------------------


class TestNotificationCallback:

    def test_on_change_called_on_add(self):
        calls = []
        registry = ToolRegistry(on_change=lambda: calls.append("changed"))
        registry.add_tool(
            name="notify-test",
            description="test",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        assert len(calls) == 1

    def test_on_change_called_on_remove(self):
        calls = []
        registry = ToolRegistry(on_change=lambda: calls.append("changed"))
        registry.add_tool(
            name="to-remove",
            description="test",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        calls.clear()
        registry.remove_tool("to-remove")
        assert len(calls) == 1

    def test_on_change_called_on_update_description(self):
        calls = []
        registry = ToolRegistry(on_change=lambda: calls.append("changed"))
        registry.add_tool(
            name="updatable",
            description="old",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        calls.clear()
        registry.update_tool("updatable", description="new")
        assert len(calls) == 1

    def test_on_change_not_called_on_metadata_only_update(self):
        calls = []
        registry = ToolRegistry(on_change=lambda: calls.append("changed"))
        registry.add_tool(
            name="meta-only",
            description="test",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
        )
        calls.clear()
        registry.update_tool("meta-only", category="web")
        # Metadata-only changes don't need to notify the MCP client
        assert len(calls) == 0

    def test_no_callback_when_notify_false(self):
        calls = []
        registry = ToolRegistry(on_change=lambda: calls.append("changed"))
        # register() with notify=False (default for builtins)
        registry.register(
            name="silent",
            description="test",
            input_schema={"type": "object"},
            handler=lambda a: {"content": [], "isError": False},
            notify=False,
        )
        assert len(calls) == 0


# ---------------------------------------------------------------------------
# Generic CLI tool wrapper
# ---------------------------------------------------------------------------


class TestGenericToolHandler:

    def test_simple_command(self):
        handler = create_generic_tool_handler("echo")
        result = handler({"target": "hello"})
        assert result["isError"] is False
        assert "hello" in result["content"][0]["text"]

    def test_with_flags(self):
        handler = create_generic_tool_handler("echo")
        result = handler({"flags": "-n", "target": "no_newline"})
        assert "no_newline" in result["content"][0]["text"]

    def test_with_args_list(self):
        handler = create_generic_tool_handler("echo")
        result = handler({"args": ["a", "b", "c"]})
        assert "a b c" in result["content"][0]["text"]

    def test_no_arguments(self):
        handler = create_generic_tool_handler("echo")
        result = handler({})
        # echo with no args should succeed
        assert result["isError"] is False

    def test_nonexistent_tool(self):
        handler = create_generic_tool_handler("nonexistent_tool_xyz")
        result = handler({})
        assert result["isError"] is True


# ---------------------------------------------------------------------------
# Integration: tools/list_changed via MCP protocol
# ---------------------------------------------------------------------------


class TestToolsListChangedNotification:

    def test_notification_sent_on_dynamic_add(self, initialized_harness: ServerHarness):
        # Call mcp_register_tool to register 'echo' (exists on all systems)
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 10,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {
                    "tool_name": "echo",
                    "tool_description": "Print text",
                    "tool_category": "general",
                },
            },
        })
        assert resp is not None
        assert "result" in resp
        # Should have received a tools/list_changed notification
        notifications = initialized_harness.get_notifications()
        methods = [n.get("method") for n in notifications]
        assert "notifications/tools/list_changed" in methods

    def test_initialize_advertises_list_changed(self, harness: ServerHarness):
        resp = harness.initialize()
        caps = resp["result"]["capabilities"]
        assert caps["tools"]["listChanged"] is True
