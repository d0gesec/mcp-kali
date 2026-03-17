"""
Tool and Resource Registry classes.

Manages registration, lookup, and execution of MCP tools and resources.
"""
import logging
import sys
import time
from typing import Any, Callable

from ..utils.validation import validate_tool_definition

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")


class ToolRegistry:
    """Stores tool definitions and dispatches tool/call requests.

    Enhanced features beyond basic registration:
      - Metadata per tool (type, category, install_method, version)
      - Execution history tracking
      - Dynamic add/remove/update at runtime
      - Search and filtering
      - Change notification callback
    """

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self._tools: dict[str, dict] = {}          # name -> MCP definition
        self._handlers: dict[str, Callable] = {}    # name -> handler function
        self._metadata: dict[str, dict] = {}        # name -> extra metadata
        self._history: dict[str, list[dict]] = {}   # name -> list of execution records
        self._on_change = on_change                 # called when tool set changes

    # -- notify ------------------------------------------------------------

    def _notify_change(self) -> None:
        if self._on_change:
            self._on_change()

    # -- registration (backwards-compatible) --------------------------------

    def register(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable[[dict], dict],
        *,
        tool_type: str = "stateless",
        category: str = "general",
        install_method: str = "builtin",
        version: str = "",
        notify: bool = False,
    ) -> None:
        """Register a tool. Backwards-compatible with the original signature."""
        self._tools[name] = {
            "name": name,
            "description": description,
            "inputSchema": input_schema,
        }
        self._handlers[name] = handler
        self._metadata[name] = {
            "type": tool_type,
            "category": category,
            "install_method": install_method,
            "version": version,
            "registered_at": time.time(),
            "usage_count": self._metadata.get(name, {}).get("usage_count", 0),
            "last_used": self._metadata.get(name, {}).get("last_used"),
        }
        if name not in self._history:
            self._history[name] = []
        if notify:
            self._notify_change()

    # -- dynamic management ------------------------------------------------

    def add_tool(
        self,
        name: str,
        description: str,
        input_schema: dict,
        handler: Callable[[dict], dict],
        *,
        tool_type: str = "stateless",
        category: str = "general",
        install_method: str = "apt",
        version: str = "",
    ) -> dict:
        """Register a new tool at runtime and notify the client.

        Returns {"success": True/False, "error": str|None}.
        """
        err = validate_tool_definition(name, description, input_schema)
        if err:
            return {"success": False, "error": err}
        self.register(
            name, description, input_schema, handler,
            tool_type=tool_type, category=category,
            install_method=install_method, version=version,
            notify=True,
        )
        log.info("Tool registry: action=add tool=%s category=%s type=%s", name, category, tool_type)
        return {"success": True, "error": None}

    def remove_tool(self, name: str) -> dict:
        """Unregister a tool and notify the client."""
        if name not in self._tools:
            return {"success": False, "error": f"Tool not found: {name}"}
        del self._tools[name]
        del self._handlers[name]
        self._metadata.pop(name, None)
        # Keep history for audit purposes
        self._notify_change()
        log.info("Tool registry: action=remove tool=%s", name)
        return {"success": True, "error": None}

    def update_tool(self, name: str, **updates: Any) -> dict:
        """Modify an existing tool's definition or metadata."""
        if name not in self._tools:
            return {"success": False, "error": f"Tool not found: {name}"}
        for key in ("description", "inputSchema"):
            if key in updates:
                self._tools[name][key] = updates[key]
        if "handler" in updates:
            self._handlers[name] = updates["handler"]
        meta_keys = {"type", "category", "install_method", "version"}
        for key in meta_keys & updates.keys():
            self._metadata[name][key] = updates[key]
        if any(k in updates for k in ("description", "inputSchema")):
            self._notify_change()
        return {"success": True, "error": None}

    # -- query -------------------------------------------------------------

    def list_tools(self) -> list[dict]:
        """Return MCP tool definitions (for tools/list response)."""
        return list(self._tools.values())

    def get_tool_info(self, name: str) -> dict | None:
        """Return full tool definition + metadata."""
        if name not in self._tools:
            return None
        return {
            **self._tools[name],
            "metadata": self._metadata.get(name, {}),
        }

    def search_tools(
        self,
        query: str | None = None,
        category: str | None = None,
        tool_type: str | None = None,
    ) -> list[dict]:
        """Search tools by name/description, category, or type."""
        results = []
        for name, definition in self._tools.items():
            meta = self._metadata.get(name, {})
            if category and meta.get("category") != category:
                continue
            if tool_type and meta.get("type") != tool_type:
                continue
            if query:
                q = query.lower()
                if q not in name.lower() and q not in definition.get("description", "").lower():
                    continue
            results.append({**definition, "metadata": meta})
        return results

    def get_tool_categories(self) -> dict[str, int]:
        """Return {category: count} mapping."""
        counts: dict[str, int] = {}
        for meta in self._metadata.values():
            cat = meta.get("category", "general")
            counts[cat] = counts.get(cat, 0) + 1
        return counts

    # -- execution ---------------------------------------------------------

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Execute a tool, track history, and return MCP content result."""
        if name not in self._handlers:
            log.warning("Tool call failed: tool=%s reason=unknown_tool", name)
            return {
                "content": [{"type": "text", "text": f"Unknown tool: {name}"}],
                "isError": True,
            }

        start = time.time()
        log.debug("Tool execution started: tool=%s", name)
        try:
            result = self._handlers[name](arguments)
        except Exception as exc:
            log.exception("Tool execution failed: tool=%s error=%s", name, str(exc))
            result = {
                "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                "isError": True,
            }
        duration = time.time() - start

        # Track execution
        output_size = sum(
            len(c.get("text", "")) for c in result.get("content", [])
        )
        record = {
            "timestamp": start,
            "arguments": arguments,
            "is_error": result.get("isError", False),
            "duration_seconds": round(duration, 3),
            "output_size": output_size,
        }

        # Log execution summary
        log.info("Tool execution finished: tool=%s duration=%.3fs output_bytes=%d status=%s",
                 name, duration, output_size,
                 "error" if result.get("isError") else "success")

        if name in self._metadata:
            self._metadata[name]["usage_count"] = (
                self._metadata[name].get("usage_count", 0) + 1
            )
            self._metadata[name]["last_used"] = start
        history = self._history.setdefault(name, [])
        history.append(record)
        # Cap history at 50 entries per tool
        if len(history) > 50:
            self._history[name] = history[-50:]

        return result

    def get_tool_history(self, name: str, limit: int = 10) -> list[dict]:
        """Return the most recent executions of a tool."""
        return self._history.get(name, [])[-limit:]


class ResourceRegistry:
    """Stores resource definitions and dispatches resources/read requests."""

    def __init__(self) -> None:
        self._resources: dict[str, dict] = {}
        self._handlers: dict[str, Callable] = {}

    def register(
        self,
        uri: str,
        name: str,
        description: str,
        mime_type: str,
        handler: Callable[[], dict],
    ) -> None:
        self._resources[uri] = {
            "uri": uri,
            "name": name,
            "description": description,
            "mimeType": mime_type,
        }
        self._handlers[uri] = handler

    def list_resources(self) -> list[dict]:
        return list(self._resources.values())

    def read_resource(self, uri: str) -> dict:
        if uri not in self._handlers:
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": f"Unknown resource: {uri}",
                    }
                ],
            }
        try:
            return self._handlers[uri]()
        except Exception as exc:
            log.exception("Resource %s raised an exception", uri)
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "text/plain",
                        "text": f"Resource error: {exc}",
                    }
                ],
            }
