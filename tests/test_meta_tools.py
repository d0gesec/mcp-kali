"""Tests for meta-tools: system_find_tool, system_install_package, mcp_register_tool."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

import pytest

from src.tools.meta_tools import handle_system_find_tool
from src.utils.rate_limiter import InstallRateLimiter

if TYPE_CHECKING:
    from conftest import ServerHarness


# ---------------------------------------------------------------------------
# system_find_tool
# ---------------------------------------------------------------------------


class TestSystemFindTool:
    """Tests for the system_find_tool meta-tool."""

    def test_find_existing_tool(self, initialized_harness: ServerHarness):
        """'echo' exists on every system."""
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_find_tool",
                "arguments": {"tool_name": "echo"},
            },
        })
        assert resp is not None
        result = resp["result"]
        assert result["isError"] is False
        data = json.loads(result["content"][0]["text"])
        assert data["available"] is True
        assert "path" in data

    def test_find_nonexistent_tool(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_find_tool",
                "arguments": {"tool_name": "totally_nonexistent_tool_xyz"},
            },
        })
        assert resp is not None
        result = resp["result"]
        assert result["isError"] is False
        data = json.loads(result["content"][0]["text"])
        assert data["available"] is False

    def test_missing_tool_name(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_find_tool",
                "arguments": {},
            },
        })
        assert resp["result"]["isError"] is True

    def test_invalid_tool_name_chars(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_find_tool",
                "arguments": {"tool_name": "nmap; rm -rf /"},
            },
        })
        assert resp["result"]["isError"] is True
        assert "Invalid" in resp["result"]["content"][0]["text"]

    def test_find_tool_direct_handler(self):
        """Test the handler function directly."""
        result = handle_system_find_tool({"tool_name": "ls"})
        assert result["isError"] is False
        data = json.loads(result["content"][0]["text"])
        assert data["available"] is True


# ---------------------------------------------------------------------------
# system_install_package — validation only (no actual apt installs)
# ---------------------------------------------------------------------------


class TestSystemInstallPackageValidation:
    """Test validation and safety checks — no actual installations."""

    def test_missing_confirm(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_install_package",
                "arguments": {"package_name": "nmap"},
            },
        })
        result = resp["result"]
        assert result["isError"] is True
        data = json.loads(result["content"][0]["text"])
        assert data["success"] is False
        assert "confirm" in data["error"]

    def test_confirm_false(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_install_package",
                "arguments": {"package_name": "nmap", "confirm": False},
            },
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is False

    def test_invalid_package_name(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_install_package",
                "arguments": {"package_name": "nmap; whoami", "confirm": True},
            },
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is False
        assert "Invalid" in data["error"]

    def test_empty_package_name(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "system_install_package",
                "arguments": {"package_name": "", "confirm": True},
            },
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is False


# ---------------------------------------------------------------------------
# InstallRateLimiter
# ---------------------------------------------------------------------------


class TestInstallRateLimiter:

    def test_allows_under_limit(self):
        limiter = InstallRateLimiter(max_per_hour=5)
        for _ in range(5):
            assert limiter.check() is True
            limiter.record()

    def test_blocks_over_limit(self):
        limiter = InstallRateLimiter(max_per_hour=2)
        limiter.record()
        limiter.record()
        assert limiter.check() is False

    def test_expires_after_hour(self):
        limiter = InstallRateLimiter(max_per_hour=1)
        # Manually inject an old timestamp
        limiter._timestamps = [time.time() - 3700]
        assert limiter.check() is True


# ---------------------------------------------------------------------------
# mcp_register_tool
# ---------------------------------------------------------------------------


class TestMcpRegisterTool:
    """Tests for the mcp_register_tool meta-tool."""

    def test_register_existing_tool(self, initialized_harness: ServerHarness):
        """Register 'ls' which exists on all systems."""
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {
                    "tool_name": "ls",
                    "tool_description": "List directory contents",
                    "tool_category": "core",
                },
            },
        })
        assert resp is not None
        result = resp["result"]
        assert result["isError"] is False
        data = json.loads(result["content"][0]["text"])
        assert data["success"] is True
        assert data["tool_name"] == "ls"
        assert data["mcp_available"] is True

    def test_register_nonexistent_tool(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {"tool_name": "totally_fake_tool_12345"},
            },
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is False
        assert "not found" in data["error"]

    def test_register_missing_tool_name(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {},
            },
        })
        assert resp["result"]["isError"] is True

    def test_registered_tool_appears_in_list(self, initialized_harness: ServerHarness):
        """After registering, the tool should appear in tools/list."""
        # Register
        initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {
                    "tool_name": "whoami",
                    "tool_description": "Print current user",
                    "tool_category": "recon",
                },
            },
        })
        # List
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
        })
        tool_names = {t["name"] for t in resp["result"]["tools"]}
        assert "whoami" in tool_names

    def test_registered_tool_is_callable(self, initialized_harness: ServerHarness):
        """After registering, the tool should be callable via tools/call."""
        # Register
        initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {
                    "tool_name": "date",
                    "tool_description": "Print current date/time",
                },
            },
        })
        # Call the newly registered tool
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "date",
                "arguments": {},
            },
        })
        result = resp["result"]
        assert result["isError"] is False
        assert "Command:" in result["content"][0]["text"]

    def test_register_with_auto_description(self, initialized_harness: ServerHarness):
        """When no description provided, should auto-detect one."""
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {"tool_name": "cat"},
            },
        })
        data = json.loads(resp["result"]["content"][0]["text"])
        assert data["success"] is True
        # Description should be non-empty and not just "CLI tool: cat"
        assert data["description"]

    def test_notification_sent_on_register(self, initialized_harness: ServerHarness):
        """Registering a tool should send a tools/list_changed notification."""
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "mcp_register_tool",
                "arguments": {
                    "tool_name": "head",
                    "tool_description": "Show first lines of file",
                },
            },
        })
        notifications = initialized_harness.get_notifications()
        methods = [n.get("method") for n in notifications]
        assert "notifications/tools/list_changed" in methods


# ---------------------------------------------------------------------------
# Meta-tools appear in tools/list
# ---------------------------------------------------------------------------


class TestMetaToolsRegistered:

    def test_all_meta_tools_present(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })
        names = {t["name"] for t in resp["result"]["tools"]}
        assert "system_find_tool" in names
        assert "system_install_package" in names
        assert "mcp_register_tool" in names

    def test_meta_tools_have_schemas(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/list",
        })
        for tool in resp["result"]["tools"]:
            if tool["name"].startswith("system_") or tool["name"].startswith("mcp_"):
                assert "inputSchema" in tool
                assert tool["inputSchema"]["type"] == "object"
                assert "properties" in tool["inputSchema"]
