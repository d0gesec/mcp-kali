"""
JSON-RPC 2.0 protocol helpers for MCP communication.
"""
import json
import sys
from typing import Any


def write_message(msg: dict) -> None:
    """Write a JSON-RPC message to stdout."""
    line = json.dumps(msg, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def error_response(req_id: Any, code: int, message: str) -> dict:
    """Create a JSON-RPC error response."""
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def success_response(req_id: Any, result: Any) -> dict:
    """Create a JSON-RPC success response."""
    return {"jsonrpc": "2.0", "id": req_id, "result": result}
