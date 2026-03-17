"""Tests for ResourceRegistry and built-in resource handlers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from src.core.registry import ResourceRegistry
from src.resources.handlers import handle_system_info

if TYPE_CHECKING:
    from conftest import ServerHarness


# ---------------------------------------------------------------------------
# ResourceRegistry unit tests
# ---------------------------------------------------------------------------


class TestResourceRegistry:
    """Unit tests for the ResourceRegistry class."""

    def test_empty_registry(self, resource_registry: ResourceRegistry):
        assert resource_registry.list_resources() == []

    def test_register_and_list(self, resource_registry: ResourceRegistry):
        resource_registry.register(
            uri="test://resource",
            name="Test Resource",
            description="A test resource",
            mime_type="text/plain",
            handler=lambda: {
                "contents": [{"uri": "test://resource", "mimeType": "text/plain", "text": "hi"}]
            },
        )
        resources = resource_registry.list_resources()
        assert len(resources) == 1
        assert resources[0]["uri"] == "test://resource"
        assert resources[0]["name"] == "Test Resource"
        assert resources[0]["mimeType"] == "text/plain"

    def test_read_registered_resource(self, resource_registry: ResourceRegistry):
        resource_registry.register(
            uri="test://data",
            name="Data",
            description="Some data",
            mime_type="application/json",
            handler=lambda: {
                "contents": [
                    {"uri": "test://data", "mimeType": "application/json", "text": '{"x":1}'}
                ]
            },
        )
        result = resource_registry.read_resource("test://data")
        assert "contents" in result
        assert result["contents"][0]["text"] == '{"x":1}'

    def test_read_unknown_resource(self, resource_registry: ResourceRegistry):
        result = resource_registry.read_resource("nope://missing")
        assert "contents" in result
        assert "Unknown resource" in result["contents"][0]["text"]

    def test_handler_exception_caught(self, resource_registry: ResourceRegistry):
        resource_registry.register(
            uri="test://bad",
            name="Bad",
            description="Fails",
            mime_type="text/plain",
            handler=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
        result = resource_registry.read_resource("test://bad")
        assert "contents" in result
        assert "Resource error" in result["contents"][0]["text"]

    def test_register_multiple(self, resource_registry: ResourceRegistry):
        for i in range(3):
            resource_registry.register(
                uri=f"test://r{i}",
                name=f"R{i}",
                description=f"Resource {i}",
                mime_type="text/plain",
                handler=lambda: {"contents": []},
            )
        assert len(resource_registry.list_resources()) == 3

    def test_overwrite_resource(self, resource_registry: ResourceRegistry):
        resource_registry.register(
            uri="test://x", name="v1", description="v1",
            mime_type="text/plain",
            handler=lambda: {"contents": [{"uri": "test://x", "mimeType": "text/plain", "text": "v1"}]},
        )
        resource_registry.register(
            uri="test://x", name="v2", description="v2",
            mime_type="text/plain",
            handler=lambda: {"contents": [{"uri": "test://x", "mimeType": "text/plain", "text": "v2"}]},
        )
        assert len(resource_registry.list_resources()) == 1
        assert resource_registry.list_resources()[0]["name"] == "v2"
        result = resource_registry.read_resource("test://x")
        assert result["contents"][0]["text"] == "v2"


# ---------------------------------------------------------------------------
# handle_system_info tests
# ---------------------------------------------------------------------------


class TestSystemInfoResource:
    """Tests for the system://info resource handler."""

    def test_returns_valid_json(self):
        result = handle_system_info()
        assert "contents" in result
        assert len(result["contents"]) == 1
        content = result["contents"][0]
        assert content["uri"] == "system://info"
        assert content["mimeType"] == "application/json"
        # The text field should be parseable JSON
        data = json.loads(content["text"])
        assert "hostname" in data
        assert "platform" in data
        assert "python_version" in data
        assert "cwd" in data

    def test_python_version_format(self):
        result = handle_system_info()
        data = json.loads(result["contents"][0]["text"])
        parts = data["python_version"].split(".")
        assert len(parts) == 3  # major.minor.patch


# ---------------------------------------------------------------------------
# MCP protocol resources/* tests via ServerHarness
# ---------------------------------------------------------------------------


class TestResourcesProtocol:
    """Test resources/list and resources/read through JSON-RPC flow."""

    def test_resources_list(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/list",
        })
        assert resp is not None
        resources = resp["result"]["resources"]
        uris = {r["uri"] for r in resources}
        assert "system://info" in uris

    def test_resources_read_system_info(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "system://info"},
        })
        assert resp is not None
        contents = resp["result"]["contents"]
        assert len(contents) == 1
        data = json.loads(contents[0]["text"])
        assert "hostname" in data

    def test_resources_read_missing_uri(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {},
        })
        assert resp is not None
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    def test_resources_read_unknown_uri(self, initialized_harness: ServerHarness):
        resp = initialized_harness.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "resources/read",
            "params": {"uri": "nope://missing"},
        })
        assert resp is not None
        # Returns success envelope with error in content
        assert "result" in resp
        assert "Unknown resource" in resp["result"]["contents"][0]["text"]
