"""
Configuration constants for the MCP Kali server.
"""
import re

# ---------------------------------------------------------------------------
# Server Information
# ---------------------------------------------------------------------------

SERVER_NAME = "pownie-kali-mcp"
SERVER_VERSION = "0.2.0"
PROTOCOL_VERSION = "2024-11-05"

# ---------------------------------------------------------------------------
# Execution Limits
# ---------------------------------------------------------------------------

DEFAULT_COMMAND_TIMEOUT = 300  # seconds
MAX_OUTPUT_BYTES = 1_048_576  # 1 MB cap per stream

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 Error Codes
# ---------------------------------------------------------------------------

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

# ---------------------------------------------------------------------------
# Security Configuration
# ---------------------------------------------------------------------------

PACKAGE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$")
MAX_INSTALLS_PER_HOUR = 10

# ---------------------------------------------------------------------------
# Session Management
# ---------------------------------------------------------------------------

MAX_SESSIONS = 20
SESSION_BUFFER_SIZE = 100 * 1024  # 100KB per session
SESSION_IDLE_TIMEOUT = 1800  # 30 minutes
SESSION_CLEANUP_INTERVAL = 60  # Check every 60 seconds
SESSION_READ_POLL_INTERVAL = 0.05  # 50ms PTY polling
SESSION_DEFAULT_READ_TIMEOUT = 1.5  # 1.5 seconds (balanced for reliability)
PTY_READ_CHUNK_SIZE = 4096  # 4KB chunks

# ---------------------------------------------------------------------------
# Proxy Configuration
# ---------------------------------------------------------------------------

PROXY_HOST = "0.0.0.0"  # Bind all interfaces (accessible from other containers)
PROXY_PORT = 8080
PROXY_FLOW_FILE = "/tmp/proxy_flows.jsonl"
PROXY_ADDON_SCRIPT = "/opt/src/proxy/addon.py"
PROXY_STARTUP_TIMEOUT = 5  # seconds to wait for mitmdump to be ready
PROXY_MAX_BODY_SIZE = 1_048_576  # 1 MB cap per request/response body
