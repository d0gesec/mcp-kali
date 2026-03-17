"""Tests for JSON-RPC 2.0 message parsing and validation."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from conftest import ServerHarness


class TestMalformedMessages:
    """Messages that aren't valid JSON or valid JSON-RPC."""

    def test_invalid_json(self, harness: ServerHarness):
        resp = harness.send_raw("{not valid json")
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32700  # PARSE_ERROR

    def test_empty_string(self, harness: ServerHarness):
        # Empty string is skipped by the main loop, but handle_message
        # would try to parse it as JSON.
        resp = harness.send_raw("")
        assert resp is not None
        assert resp["error"]["code"] == -32700

    def test_json_array_instead_of_object(self, harness: ServerHarness):
        resp = harness.send_raw('[1, 2, 3]')
        assert resp is not None
        assert resp["error"]["code"] == -32600  # INVALID_REQUEST

    def test_json_string_instead_of_object(self, harness: ServerHarness):
        resp = harness.send_raw('"just a string"')
        assert resp is not None
        assert resp["error"]["code"] == -32600

    def test_json_number(self, harness: ServerHarness):
        resp = harness.send_raw("42")
        assert resp is not None
        assert resp["error"]["code"] == -32600

    def test_null(self, harness: ServerHarness):
        resp = harness.send_raw("null")
        assert resp is not None
        assert resp["error"]["code"] == -32600


class TestMissingJsonRpcVersion:
    """Object but missing or wrong jsonrpc field."""

    def test_missing_jsonrpc_field(self, harness: ServerHarness):
        resp = harness.send_raw(json.dumps({"id": 1, "method": "ping"}))
        assert resp is not None
        assert resp["error"]["code"] == -32600

    def test_wrong_jsonrpc_version(self, harness: ServerHarness):
        resp = harness.send_raw(
            json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping"})
        )
        assert resp is not None
        assert resp["error"]["code"] == -32600

    def test_jsonrpc_as_number(self, harness: ServerHarness):
        resp = harness.send_raw(
            json.dumps({"jsonrpc": 2.0, "id": 1, "method": "ping"})
        )
        assert resp is not None
        assert resp["error"]["code"] == -32600


class TestUnknownMethod:
    """Valid JSON-RPC but method not recognized."""

    def test_unknown_method(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "bogus/method",
        })
        assert resp is not None
        assert resp["error"]["code"] == -32601  # METHOD_NOT_FOUND
        assert "bogus/method" in resp["error"]["message"]

    def test_empty_method(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "",
        })
        assert resp is not None
        assert resp["error"]["code"] == -32601


class TestResponseStructure:
    """Verify JSON-RPC 2.0 response structure."""

    def test_success_response_has_required_fields(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 42,
            "method": "ping",
        })
        assert resp is not None
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 42
        assert "result" in resp
        assert "error" not in resp

    def test_error_response_has_required_fields(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": 99,
            "method": "nonexistent",
        })
        assert resp is not None
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 99
        assert "error" in resp
        assert "code" in resp["error"]
        assert "message" in resp["error"]
        assert "result" not in resp

    def test_response_preserves_string_id(self, harness: ServerHarness):
        resp = harness.send({
            "jsonrpc": "2.0",
            "id": "abc-123",
            "method": "ping",
        })
        assert resp is not None
        assert resp["id"] == "abc-123"

    def test_response_preserves_null_id_for_parse_error(self, harness: ServerHarness):
        resp = harness.send_raw("broken{json")
        assert resp is not None
        assert resp["id"] is None
