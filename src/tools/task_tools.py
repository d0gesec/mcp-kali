"""
Background task tool handlers for MCP.

Provides handlers for task_get_output, task_list, and task_stop tools
that interact with the BackgroundTaskManager.
"""
import json
import logging
import sys
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from ..core.server import MCPServer

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")


def make_task_handlers(server: "MCPServer") -> dict[str, Callable[[dict], dict]]:
    """
    Create all background task handlers bound to the server's BackgroundTaskManager.

    Args:
        server: MCPServer instance with task_manager attribute

    Returns:
        Dictionary mapping handler names to handler functions
    """

    def handle_task_get_output(args: dict) -> dict:
        """
        Handler for task_get_output tool.

        Retrieves output from a background task. Blocks by default until
        task completes or new output appears (up to timeout seconds).
        """
        task_id = args.get("task_id")
        tail_lines = args.get("tail_lines")
        wait = args.get("wait", True)
        timeout = args.get("timeout", 30)

        # Validation
        if not task_id or not isinstance(task_id, str):
            log.warning("Task get_output failed: reason=missing_task_id")
            return {
                "content": [{"type": "text", "text": "Missing required parameter: task_id"}],
                "isError": True,
            }

        if tail_lines is not None:
            if not isinstance(tail_lines, int) or tail_lines < 1:
                tail_lines = None

        if not isinstance(timeout, int) or timeout < 1:
            timeout = 30

        log.debug("Getting task output: task_id=%s tail_lines=%s wait=%s timeout=%d",
                  task_id, tail_lines, wait, timeout)

        result = server.task_manager.get_task_output(
            task_id, tail_lines=tail_lines, wait=bool(wait), timeout=timeout
        )

        # Format response
        is_error = "error" in result

        if is_error:
            text = f"Error: {result['error']}"
            log.warning("Task get_output failed: task_id=%s error=%s",
                       task_id, result.get("error"))
        else:
            # Format output with status header
            status = result["status"]
            exit_code = result["exit_code"]
            runtime = result["runtime"]
            output = result["output"]

            # Build status line
            status_parts = [f"Status: {status}"]
            if exit_code is not None:
                status_parts.append(f"Exit Code: {exit_code}")
            status_parts.append(f"Runtime: {runtime}s")

            status_line = " | ".join(status_parts)

            # Combine status and output
            if output:
                text = f"{status_line}\n\n{output}"
            else:
                text = f"{status_line}\n\n(no output yet)"

            log.debug("Task get_output completed: task_id=%s status=%s output_bytes=%d",
                     task_id, status, len(output))

        return {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }

    def handle_task_list(args: dict) -> dict:
        """
        Handler for task_list tool.

        Lists all background tasks with their status.
        """
        log.debug("Listing background tasks")

        tasks = server.task_manager.list_tasks()

        # Format as JSON for readability
        result = {
            "tasks": tasks,
            "total": len(tasks),
        }

        text = json.dumps(result, indent=2)

        log.debug("Task list: total=%d", len(tasks))

        return {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        }

    def handle_task_stop(args: dict) -> dict:
        """
        Handler for task_stop tool.

        Stops a running background task.
        """
        task_id = args.get("task_id")

        # Validation
        if not task_id or not isinstance(task_id, str):
            log.warning("Task stop failed: reason=missing_task_id")
            return {
                "content": [{"type": "text", "text": "Missing required parameter: task_id"}],
                "isError": True,
            }

        log.info("Stopping task: task_id=%s", task_id)

        result = server.task_manager.stop_task(task_id)

        # Format response
        is_error = "error" in result

        if is_error:
            text = f"Error: {result['error']}"
            log.warning("Task stop failed: task_id=%s error=%s",
                       task_id, result.get("error"))
        else:
            text = f"Task stopped: {task_id} (exit code: {result.get('exit_code')})"
            log.info("Task stopped successfully: task_id=%s", task_id)

        return {
            "content": [{"type": "text", "text": text}],
            "isError": is_error,
        }

    return {
        "task_get_output": handle_task_get_output,
        "task_list": handle_task_list,
        "task_stop": handle_task_stop,
    }
