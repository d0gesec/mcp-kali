"""Shared fixtures and helpers for MCP server tests."""

import json
import sys
from pathlib import Path

import pytest

# Make src module importable from the parent directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.server import MCPServer  # noqa: E402
from src.core.registry import ResourceRegistry, ToolRegistry  # noqa: E402
from src.utils.subprocess import execute_subprocess  # noqa: E402


# ---------------------------------------------------------------------------
# ServerHarness — drives MCPServer without real stdin/stdout
# ---------------------------------------------------------------------------


class ServerHarness:
    """Wraps MCPServer so tests can send messages and collect responses
    without touching real stdin/stdout."""

    def __init__(self) -> None:
        self.server = MCPServer()
        self.responses: list[dict] = []
        self.all_messages: list[dict] = []  # includes notifications
        # Monkey-patch _write to capture all outbound messages
        self.server._write = self._capture  # type: ignore[assignment]

    def _capture(self, msg: dict) -> None:
        self.all_messages.append(msg)
        # Only treat messages with "id" as request responses
        if "id" in msg:
            self.responses.append(msg)

    def send(self, message: dict) -> dict | None:
        """Send a JSON-RPC message and return the first response (if any)."""
        self.responses.clear()
        self.all_messages.clear()
        raw = json.dumps(message)
        self.server.handle_message(raw)
        return self.responses[0] if self.responses else None

    def send_raw(self, raw: str) -> dict | None:
        """Send a raw string (for testing malformed JSON)."""
        self.responses.clear()
        self.all_messages.clear()
        self.server.handle_message(raw)
        return self.responses[0] if self.responses else None

    def get_notifications(self) -> list[dict]:
        """Return notification messages from the last send (no id field)."""
        return [m for m in self.all_messages if "id" not in m]

    def initialize(self) -> dict | None:
        """Shortcut: perform the initialize handshake."""
        return self.send({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0"},
            },
        })


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def harness() -> ServerHarness:
    """Fresh MCPServer wrapped in a test harness."""
    return ServerHarness()


@pytest.fixture
def initialized_harness(harness: ServerHarness) -> ServerHarness:
    """MCPServer that has already completed the initialize handshake."""
    harness.initialize()
    return harness


@pytest.fixture
def tool_registry() -> ToolRegistry:
    """Empty ToolRegistry for unit tests."""
    return ToolRegistry()


@pytest.fixture
def resource_registry() -> ResourceRegistry:
    """Empty ResourceRegistry for unit tests."""
    return ResourceRegistry()
