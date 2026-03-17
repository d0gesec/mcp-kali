"""
Session management tool handlers for MCP.

Provides handlers for session_create, session_send, session_list, and session_close
tools that interact with the SessionManager.
"""
import json
import logging
import sys
from typing import TYPE_CHECKING, Callable

from ..config.constants import SESSION_DEFAULT_READ_TIMEOUT

if TYPE_CHECKING:
    from ..core.server import MCPServer

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")


def make_session_handlers(server: "MCPServer") -> dict[str, Callable[[dict], dict]]:
    """
    Create all session handlers bound to the server's SessionManager.

    Args:
        server: MCPServer instance with session_manager attribute

    Returns:
        Dictionary mapping handler names to handler functions
    """

    def handle_session_create(args: dict) -> dict:
        """
        Handler for session_create tool.

        Creates a new persistent PTY session for interactive commands.
        """
        command = args.get("command")
        name = args.get("name")
        timeout = args.get("timeout", 300)

        # Validation
        if not command or not isinstance(command, str):
            log.warning("Session create failed: reason=missing_command")
            return {
                "content": [{"type": "text", "text": "Missing required parameter: command"}],
                "isError": True,
            }

        if not isinstance(timeout, int) or timeout < 1:
            timeout = 300

        log.info("Creating session: command='%s' name=%s", command[:50], name or "unnamed")

        result = server.session_manager.create_session(command, name, timeout)

        # Format response - simple text for LLM readability
        is_error = "error" in result

        if is_error:
            text = f"Failed: {result['error']}"
            log.warning("Session creation failed: error=%s", result.get("error"))
        else:
            text = f"Session created: {result['session_id']}"
            log.info("Session created successfully: session_id=%s", result.get("session_id"))

        return {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }

    def handle_session_send(args: dict) -> dict:
        """
        Handler for session_send tool.

        Sends input to a session and reads buffered output.
        """
        session_id = args.get("session_id")
        input_data = args.get("input", "")
        read_timeout = args.get("read_timeout", SESSION_DEFAULT_READ_TIMEOUT)

        # Validation
        if not session_id or not isinstance(session_id, str):
            log.warning("Session send failed: reason=missing_session_id")
            return {
                "content": [{"type": "text", "text": "Missing required parameter: session_id"}],
                "isError": True,
            }

        if not isinstance(input_data, str):
            input_data = ""

        if not isinstance(read_timeout, int) or read_timeout < 0:
            read_timeout = SESSION_DEFAULT_READ_TIMEOUT

        log.debug("Session send: session_id=%s input_len=%d read_timeout=%d",
                 session_id, len(input_data), read_timeout)

        result = server.session_manager.send_to_session(session_id, input_data, read_timeout)

        # Format response - LLM-friendly with session_id and raw output
        is_error = "error" in result

        if is_error:
            text = f"Failed: {result['error']}"
            log.warning("Session send failed: session_id=%s error=%s",
                       session_id, result.get("error"))
        else:
            # Success: show session_id and raw terminal output
            output = result.get("output", "")
            output_len = len(output)
            status = result.get("status", "unknown")
            alive = result.get("alive", True)
            since_output = result.get("since_output", 0)
            exit_code = result.get("exit_code")

            # Build status line for diagnostic info
            status_parts = [f"status={status}"]
            if not alive:
                status_parts.append("DEAD")
                if exit_code is not None:
                    status_parts.append(f"exit={exit_code}")
            if since_output > 2:
                status_parts.append(f"silent={since_output}s")

            status_line = f"[{' '.join(status_parts)}]"

            # Format output with diagnostic info when empty
            if output:
                text = f"session_id: {session_id} {status_line}\n{output}"
            else:
                # Provide clear diagnostic info when no output
                if not alive:
                    reason = f"process exited (code={exit_code})" if exit_code is not None else "process died"
                    text = f"session_id: {session_id} {status_line}\n(no output - {reason})"
                elif since_output > 5:
                    text = f"session_id: {session_id} {status_line}\n(no output - process alive but silent for {since_output}s, may be waiting for input or hanging)"
                else:
                    text = f"session_id: {session_id} {status_line}\n(no output yet - process running)"

            log.debug("Session send completed: session_id=%s output_len=%d status=%s alive=%s",
                     session_id, output_len, status, alive)

        return {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }

    def handle_session_list(args: dict) -> dict:
        """
        Handler for session_list tool.

        Lists all active sessions with metadata.
        """
        log.debug("Listing sessions")

        sessions = server.session_manager.list_sessions()

        result = {
            "sessions": sessions,
            "total": len(sessions),
        }

        text = json.dumps(result, indent=2)

        log.debug("Session list: total=%d", len(sessions))

        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }

    def handle_session_close(args: dict) -> dict:
        """
        Handler for session_close tool.

        Terminates a session and cleans up resources.
        """
        session_id = args.get("session_id")

        # Validation
        if not session_id or not isinstance(session_id, str):
            log.warning("Session close failed: reason=missing_session_id")
            return {
                "content": [{"type": "text", "text": "Missing required parameter: session_id"}],
                "isError": True,
            }

        log.info("Closing session: session_id=%s", session_id)

        result = server.session_manager.close_session(session_id)

        # Format response - simple text for LLM readability
        is_error = "error" in result

        if is_error:
            text = f"Failed: {result['error']}"
            log.warning("Session close failed: session_id=%s error=%s",
                       session_id, result.get("error"))
        else:
            text = "closed"
            log.info("Session closed successfully: session_id=%s", session_id)

        return {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }

    return {
        "session_create": handle_session_create,
        "session_send": handle_session_send,
        "session_list": handle_session_list,
        "session_close": handle_session_close,
    }
