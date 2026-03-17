"""
MCP Server implementation.

A JSON-RPC 2.0 / MCP server communicating over stdin/stdout.
"""
import json
import logging
import sys
from typing import Any, Callable

from ..config.constants import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
)
from ..core.protocol import error_response, success_response, write_message
from ..core.registry import ResourceRegistry, ToolRegistry
from ..core.session_manager import SessionManager
from ..core.task_manager import BackgroundTaskManager
from ..resources.handlers import handle_system_info
from ..tools.core_tools import make_execute_command_handler, handle_list_files
from ..tools.meta_tools import make_install_handler, make_register_handler, handle_system_find_tool
from ..middleware.tracing import init_tracer, reconstruct_context
from ..proxy.manager import ProxyManager
from ..tools.proxy_tools import make_proxy_handlers
# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(SERVER_NAME)


class MCPServer:
    """JSON-RPC 2.0 / MCP server communicating over stdin/stdout."""

    def __init__(self) -> None:
        log.info("Server initialization: phase=registry_setup")
        self.tools = ToolRegistry(on_change=self._send_tools_list_changed)
        self.resources = ResourceRegistry()
        self.session_manager = SessionManager()
        self.task_manager = BackgroundTaskManager()
        self.proxy_manager = ProxyManager()
        self.tracer = init_tracer()
        self._running = False
        self._initialized = False
        log.info("Server initialization: phase=registering_builtins")
        self._register_builtins()
        log.info("Server initialization: phase=complete builtin_tools=%d builtin_resources=%d",
                 len(self.tools.list_tools()), len(self.resources.list_resources()))

    # -- protocol methods --------------------------------------------------

    def _write(self, msg: dict) -> None:
        """Write a JSON-RPC message. Can be monkey-patched for testing."""
        write_message(msg)

    # -- notifications -----------------------------------------------------

    def _send_tools_list_changed(self) -> None:
        """Notify the MCP client that the tool list has changed."""
        self._write({
            "jsonrpc": "2.0",
            "method": "notifications/tools/list_changed",
        })
        log.info("MCP Server notification: type=tools_list_changed tool_count=%d",
                 len(self.tools.list_tools()))

    # -- registration ------------------------------------------------------

    def _register_builtins(self) -> None:
        # --- Core tools ---
        self.tools.register(
            name="execute_command",
            description="Execute a shell command and return output",
            input_schema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default 300)",
                    },
                    "run_in_background": {
                        "type": "boolean",
                        "description": "Run command in background and return immediately with task_id (default false)",
                    },
                    "name": {
                        "type": "string",
                        "description": "Optional friendly name for background task",
                    },
                },
                "required": ["command"],
            },
            handler=make_execute_command_handler(self.task_manager),
            category="core",
        )

        self.tools.register(
            name="list_files",
            description="List files in a directory",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path (default /workspace)",
                    },
                    "recursive": {
                        "type": "boolean",
                        "description": "List recursively (default false)",
                    },
                },
            },
            handler=handle_list_files,
            category="core",
        )

        # --- Meta-tools for dynamic tool management ---
        self.tools.register(
            name="system_find_tool",
            description=(
                "Check if a command-line tool is available on the system. "
                "Returns whether it's installed, its path, or whether it can "
                "be installed via apt."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the tool to check (e.g. 'nmap', 'sqlmap')",
                    },
                },
                "required": ["tool_name"],
            },
            handler=handle_system_find_tool,
            category="meta",
        )

        self.tools.register(
            name="system_install_package",
            description=(
                "Install a package using the apt package manager. "
                "Requires confirm=true for safety. Automatically registers "
                "the installed tool as an MCP tool if possible."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "package_name": {
                        "type": "string",
                        "description": "Name of the apt package to install",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to proceed (safety check)",
                        "default": False,
                    },
                },
                "required": ["package_name", "confirm"],
            },
            handler=make_install_handler(self),
            category="meta",
        )

        self.tools.register(
            name="mcp_register_tool",
            description=(
                "Register an already-installed command-line tool as an MCP tool "
                "so it appears in tools/list. The tool must exist in PATH."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Name of the installed tool to register",
                    },
                    "tool_description": {
                        "type": "string",
                        "description": "What the tool does (auto-detected if omitted)",
                    },
                    "tool_category": {
                        "type": "string",
                        "description": "Category: recon, exploit, crypto, forensics, web, pwn, etc.",
                        "default": "general",
                    },
                },
                "required": ["tool_name"],
            },
            handler=make_register_handler(self),
            category="meta",
        )

        # --- Session management tools ---
        from ..tools.session_tools import make_session_handlers
        from ..config.schemas import (
            SESSION_CREATE_SCHEMA,
            SESSION_SEND_SCHEMA,
            SESSION_LIST_SCHEMA,
            SESSION_CLOSE_SCHEMA,
        )

        session_handlers = make_session_handlers(self)

        self.tools.register(
            name="session_create",
            description="Start a new persistent PTY session for interactive commands (telnet, SSH, netcat, etc.)",
            input_schema=SESSION_CREATE_SCHEMA,
            handler=session_handlers["session_create"],
            category="session",
        )

        self.tools.register(
            name="session_send",
            description="Send input to a session and read buffered output",
            input_schema=SESSION_SEND_SCHEMA,
            handler=session_handlers["session_send"],
            category="session",
        )

        self.tools.register(
            name="session_list",
            description="List all active sessions with metadata",
            input_schema=SESSION_LIST_SCHEMA,
            handler=session_handlers["session_list"],
            category="session",
        )

        self.tools.register(
            name="session_close",
            description="Terminate a session and clean up resources",
            input_schema=SESSION_CLOSE_SCHEMA,
            handler=session_handlers["session_close"],
            category="session",
        )

        # --- Background task management tools ---
        from ..tools.task_tools import make_task_handlers
        from ..config.schemas import (
            TASK_GET_OUTPUT_SCHEMA,
            TASK_LIST_SCHEMA,
            TASK_STOP_SCHEMA,
        )

        task_handlers = make_task_handlers(self)

        self.tools.register(
            name="task_get_output",
            description="Get output from a background task started with execute_command. Blocks by default (up to 30s) until task completes or new output appears. Use wait=false for instant poll.",
            input_schema=TASK_GET_OUTPUT_SCHEMA,
            handler=task_handlers["task_get_output"],
            category="background",
        )

        self.tools.register(
            name="task_list",
            description="List all background tasks with their status",
            input_schema=TASK_LIST_SCHEMA,
            handler=task_handlers["task_list"],
            category="background",
        )

        self.tools.register(
            name="task_stop",
            description="Stop a running background task",
            input_schema=TASK_STOP_SCHEMA,
            handler=task_handlers["task_stop"],
            category="background",
        )

        # --- Proxy tools ---
        from ..config.schemas import (
            PROXY_START_SCHEMA,
            PROXY_GET_FLOWS_SCHEMA,
            PROXY_EXPORT_SCHEMA,
            PROXY_REPLAY_SCHEMA,
        )

        proxy_handlers = make_proxy_handlers(self.proxy_manager)
        proxy_defs: list[tuple[str, str, dict]] = [
            (
                "proxy_start",
                "Start the mitmproxy intercepting proxy on port 8080. Route traffic with: curl -x http://127.0.0.1:8080 http://target",
                PROXY_START_SCHEMA,
            ),
            (
                "proxy_get_flows",
                "Get captured HTTP request/response flows from the intercepting proxy. Shows method, URL, status code, and body size.",
                PROXY_GET_FLOWS_SCHEMA,
            ),
            (
                "proxy_export",
                "Export a captured HTTP flow as raw HTTP request text, compatible with sqlmap -r format. Specify flow by index or URL filter.",
                PROXY_EXPORT_SCHEMA,
            ),
            (
                "proxy_replay",
                "Replay a captured HTTP request with optional modifications to headers, body, or method. Useful for parameter tampering and injection testing.",
                PROXY_REPLAY_SCHEMA,
            ),
        ]
        for name, desc, schema in proxy_defs:
            self.tools.register(
                name=name,
                description=desc,
                input_schema=schema,
                handler=proxy_handlers[name],
                category="proxy",
            )

        # --- Resources ---
        self.resources.register(
            uri="system://info",
            name="System Information",
            description="Host and runtime information",
            mime_type="application/json",
            handler=handle_system_info,
        )

        self.resources.register(
            uri="proxy://status",
            name="Proxy Status",
            description="Current proxy state: running, PID, flow count",
            mime_type="application/json",
            handler=lambda: {
                "contents": [{
                    "uri": "proxy://status",
                    "mimeType": "application/json",
                    "text": json.dumps(self.proxy_manager.get_status(), indent=2),
                }],
            },
        )

    # -- method handlers ---------------------------------------------------

    def _handle_initialize(self, req_id: Any, params: dict) -> None:
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {},
            },
            "serverInfo": {
                "name": SERVER_NAME,
                "version": SERVER_VERSION,
            },
        }
        self._write(success_response(req_id, result))
        self._initialized = True
        client_info = params.get("clientInfo", {})
        log.info("MCP Server handshake: status=initialized client_name=%s client_version=%s",
                 client_info.get("name", "unknown"), client_info.get("version", "unknown"))

    def _handle_ping(self, req_id: Any) -> None:
        self._write(success_response(req_id, {}))

    def _handle_tools_list(self, req_id: Any) -> None:
        self._write(success_response(req_id, {"tools": self.tools.list_tools()}))

    def _handle_tools_call(self, req_id: Any, params: dict) -> None:
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not name:
            self._write(error_response(req_id, INVALID_PARAMS, "Missing tool name"))
            return

        # Extract and strip trace context (injected by PreToolUse hook)
        otel_trace = arguments.pop("_otel_trace", None)

        # Log the tool call with arguments
        log.info("Tool call initiated: tool=%s request_id=%s", name, req_id)
        log.debug("Tool call arguments: tool=%s args=%s", name, json.dumps(arguments))

        # Create OTLP span (child of PreToolUse root span if trace context present)
        span_ctx = None
        if otel_trace:
            try:
                span_ctx = reconstruct_context(
                    otel_trace["trace_id"], otel_trace["parent_span_id"]
                )
            except Exception:
                log.debug("Failed to reconstruct trace context, proceeding without parent span")

        # Extract command info for span attributes
        import re
        cmd = arguments.get("command", "") or arguments.get("input", "")
        ips = re.findall(r'[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+', cmd) if cmd else []

        with self.tracer.start_as_current_span("mcp.execution", context=span_ctx) as span:
            span.set_attribute("tool.name", name)
            span.set_attribute("rpc.request_id", str(req_id))
            if cmd:
                span.set_attribute("command.full", cmd[:2000])
            if ips:
                span.set_attribute("target.ip", ips[0])

            result = self.tools.call_tool(name, arguments)

            is_error = result.get("isError", False)
            output_text = ""
            for c in result.get("content", []):
                if c.get("type") == "text":
                    output_text = c.get("text", "")
                    break
            span.set_attribute("execution.is_error", is_error)
            span.set_attribute("execution.output_bytes", len(output_text))
            span.set_attribute("result.summary", output_text[:2000])

        log.info("Tool call completed: tool=%s request_id=%s status=%s",
                 name, req_id, "error" if is_error else "success")

        self._write(success_response(req_id, result))

    def _handle_resources_list(self, req_id: Any) -> None:
        self._write(
            success_response(req_id, {"resources": self.resources.list_resources()})
        )

    def _handle_resources_read(self, req_id: Any, params: dict) -> None:
        uri = params.get("uri")
        if not uri:
            self._write(error_response(req_id, INVALID_PARAMS, "Missing resource URI"))
            return
        result = self.resources.read_resource(uri)
        self._write(success_response(req_id, result))

    # -- message router ----------------------------------------------------

    def handle_message(self, raw: str) -> None:
        """Parse and route a single JSON-RPC message."""
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._write(error_response(None, PARSE_ERROR, f"Parse error: {exc}"))
            return

        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            self._write(
                error_response(
                    msg.get("id") if isinstance(msg, dict) else None,
                    INVALID_REQUEST,
                    "Invalid JSON-RPC 2.0 request",
                )
            )
            return

        method = msg.get("method", "")
        req_id = msg.get("id")  # None for notifications
        params = msg.get("params", {})

        log.debug("← %s (id=%s)", method, req_id)

        # Notifications (no id) — no response expected
        if req_id is None:
            if method == "notifications/initialized":
                log.info("MCP Server notification received: type=client_initialized")
            else:
                log.debug("MCP Server notification received: type=%s action=ignored", method)
            return

        # Requests (have id) — must respond
        handlers: dict[str, Callable] = {
            "initialize": lambda: self._handle_initialize(req_id, params),
            "ping": lambda: self._handle_ping(req_id),
            "tools/list": lambda: self._handle_tools_list(req_id),
            "tools/call": lambda: self._handle_tools_call(req_id, params),
            "resources/list": lambda: self._handle_resources_list(req_id),
            "resources/read": lambda: self._handle_resources_read(req_id, params),
        }

        handler = handlers.get(method)
        if handler:
            handler()
        else:
            self._write(
                error_response(req_id, METHOD_NOT_FOUND, f"Unknown method: {method}")
            )

    # -- main loop ---------------------------------------------------------

    def run(self) -> None:
        """Read lines from stdin and process them until EOF or shutdown."""
        self._running = True
        log.info("MCP Server main loop: status=running mode=stdin_listener")

        message_count = 0
        while self._running:
            try:
                line = sys.stdin.readline()
                if not line:
                    log.info("MCP Server main loop: status=shutdown reason=stdin_closed")
                    break
                line = line.strip()
                if not line:
                    continue
                message_count += 1
                self.handle_message(line)
            except KeyboardInterrupt:
                log.info("MCP Server main loop: status=interrupted reason=keyboard_interrupt")
                break
            except Exception as exc:
                log.exception("MCP Server main loop: status=error error=%s", str(exc))

        log.info("MCP Server main loop: status=stopped messages_processed=%d", message_count)
        self.shutdown()

    def shutdown(self) -> None:
        self._running = False

        # Clean up active synchronous subprocesses first
        from ..utils.subprocess import cleanup_all_processes
        cleanup_all_processes()

        # Clean up proxy, sessions, and background tasks
        self.proxy_manager.shutdown()
        self.session_manager.shutdown()
        self.task_manager.shutdown()

        log.info("MCP Server shutdown: status=complete tools_registered=%d",
                 len(self.tools.list_tools()))
