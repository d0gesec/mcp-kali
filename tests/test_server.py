"""Tests for MCPServer protocol methods (initialize, ping, lifecycle)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from src.config.constants import PROTOCOL_VERSION, SERVER_NAME, SERVER_VERSION

if TYPE_CHECKING:
    from conftest import ServerHarness


# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    """Tests for the initialize handshake."""

    def test_initialize_response_structure(self, harness: ServerHarness):
        resp = harness.initialize()
        assert resp is not None
        result = resp["result"]
        assert result["protocolVersion"] == PROTOCOL_VERSION
        assert "capabilities" in result
        assert "tools" in result["capabilities"]
        assert "resources" in result["capabilities"]
        assert result["serverInfo"]["name"] == SERVER_NAME
        assert result["serverInfo"]["version"] == SERVER_VERSION

    def test_initialize_with_client_info(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"sampling": {}},
                "clientInfo": {"name": "claude-code", "version": "1.2.3"},
            },
        })
        assert resp is not None
        assert "result" in resp

    def test_initialize_without_params(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
        })
        # Should still work — params defaults to {}
        assert resp is not None
        assert "result" in resp

    def test_double_initialize(self, harness: ServerHarness):
        resp1 = harness.initialize()
        resp2 = harness.initialize()
        # Should succeed both times (server is lenient)
        assert resp1 is not None and "result" in resp1
        assert resp2 is not None and "result" in resp2


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


class TestPing:
    """Tests for the ping method."""

    def test_ping_returns_empty_result(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "ping",
        })
        assert resp is not None
        assert resp["result"] == {}

    def test_ping_preserves_id(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": "ping-123",
            "method": "ping",
        })
        assert resp["id"] == "ping-123"


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestNotifications:
    """Verify notification handling (no response expected)."""

    def test_initialized_notification_no_response(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        })
        assert resp is None

    def test_cancelled_notification_no_response(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": 5, "reason": "user cancelled"},
        })
        assert resp is None


# ---------------------------------------------------------------------------
# MCPServer state
# ---------------------------------------------------------------------------


class TestServerState:

    def test_initialized_flag_set_after_init(self, harness: ServerHarness):
        assert harness.server._initialized is False
        harness.initialize()
        assert harness.server._initialized is True

    def test_shutdown_sets_running_false(self, harness: ServerHarness):
        harness.server._running = True
        harness.server.shutdown()
        assert harness.server._running is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:

    def test_params_missing_defaults_to_empty_dict(self, harness: ServerHarness):
        # tools/call with no params key at all
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
        })
        assert resp is not None
        # Should get INVALID_PARAMS because name is missing from empty params
        assert "error" in resp

    def test_large_id_number(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 999999999999,
            "method": "ping",
        })
        assert resp["id"] == 999999999999

    def test_zero_id(self, harness: ServerHarness):
        # id=0 is valid and should not be treated as "no id"
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "ping",
        })
        assert resp is not None
        assert resp["id"] == 0
        assert "result" in resp
