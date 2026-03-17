"""
Core built-in tool handlers.
"""
import logging
import os
import sys
from typing import TYPE_CHECKING

from ..config.constants import DEFAULT_COMMAND_TIMEOUT
from ..utils.subprocess import execute_subprocess

if TYPE_CHECKING:
    from ..core.task_manager import BackgroundTaskManager

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")


def make_execute_command_handler(task_manager: "BackgroundTaskManager | None" = None):
    """
    Create execute_command handler with optional background task support.

    Args:
        task_manager: Optional BackgroundTaskManager for background execution

    Returns:
        Handler function for execute_command
    """
    def handle_execute_command(args: dict) -> dict:
        """Execute a shell command inside the container."""
        command = args.get("command")
        if not command or not isinstance(command, str):
            log.warning("Command execution failed: reason=missing_command")
            return {
                "content": [{"type": "text", "text": "Missing required parameter: command"}],
                "isError": True,
            }

        timeout = args.get("timeout", DEFAULT_COMMAND_TIMEOUT)
        if not isinstance(timeout, int) or timeout < 1:
            timeout = DEFAULT_COMMAND_TIMEOUT

        run_in_background = args.get("run_in_background", False)
        task_name = args.get("name")

        # Background execution
        if run_in_background:
            if task_manager is None:
                log.error("Background execution requested but task_manager not available")
                return {
                    "content": [{"type": "text", "text": "Background execution not supported"}],
                    "isError": True,
                }

            log.info("Creating background task: cmd='%s' timeout=%d name=%s",
                    command[:100], timeout, task_name or "unnamed")

            result = task_manager.create_task(command, timeout=timeout, name=task_name)

            if "error" in result:
                log.error("Background task creation failed: error=%s", result["error"])
                return {
                    "content": [{"type": "text", "text": f"Failed to create background task: {result['error']}"}],
                    "isError": True,
                }

            task_id = result["task_id"]
            output_file = result["output_file"]
            task_name = result["name"]

            text = f"Background task started:\n  Task ID: {task_id}\n  Name: {task_name}\n  Output: {output_file}\n\nUse task_get_output to retrieve results."

            log.info("Background task started: task_id=%s output=%s", task_id, output_file)

            return {"content": [{"type": "text", "text": text}], "isError": False}

        # Synchronous execution
        log.info("Executing command: cmd='%s' timeout=%d", command, timeout)

        result = execute_subprocess(command, timeout=timeout)

        # Log command execution results
        log.info("Command completed: exit_code=%d timed_out=%s stdout_bytes=%d stderr_bytes=%d",
                 result['exit_code'], result['timed_out'],
                 len(result['stdout']), len(result['stderr']))

        # Always log stderr for debugging
        if result['stderr']:
            log.warning("Command stderr: %s", result['stderr'][:500])

        # Build output with full diagnostic context for the LLM.
        # The agent needs exit code + stderr to interpret failures correctly.
        # Suppressing these "to save tokens" causes the agent to get stuck
        # in reasoning loops when commands fail silently.
        stdout = result['stdout']
        stderr = result['stderr']
        exit_code = result['exit_code']

        if stdout and stderr and stderr.strip() != stdout.strip():
            # Both streams have different content — show both
            text = stdout
            # Append stderr if it contains meaningful diagnostic info
            # (skip if it's just warnings duplicating stdout)
            stderr_trimmed = stderr.strip()
            if len(stderr_trimmed) <= 2000:
                text += f"\n[stderr]: {stderr_trimmed}"
            else:
                text += f"\n[stderr]: {stderr_trimmed[:2000]}... (truncated)"
        elif stdout:
            text = stdout
        elif stderr:
            text = stderr
        else:
            text = "(no output)"

        # Always append exit code — the agent needs this to distinguish
        # silent success (exit 0) from silent failure (exit 1+)
        if exit_code != 0:
            text += f"\n[exit_code: {exit_code}]"

        # Add timeout indicator if needed
        if result["timed_out"]:
            text += f"\n[TIMED OUT after {timeout}s — partial output above]"
            log.warning("Command timed out: cmd='%s' timeout=%d", command, timeout)

        return {"content": [{"type": "text", "text": text}], "isError": False}

    return handle_execute_command


def handle_list_files(args: dict) -> dict:
    """List files in a directory."""
    path = args.get("path", "/workspace")
    if not isinstance(path, str):
        path = "/workspace"
    recursive = args.get("recursive", False)

    log.info("Listing files: path='%s' recursive=%s", path, recursive)

    if not os.path.isdir(path):
        log.warning("List files failed: path='%s' reason=not_a_directory", path)
        return {
            "content": [{"type": "text", "text": f"Not a directory: {path}"}],
            "isError": True,
        }

    try:
        if recursive:
            lines: list[str] = []
            for root, dirs, files in os.walk(path):
                level = root.replace(path, "").count(os.sep)
                indent = "  " * level
                lines.append(f"{indent}{os.path.basename(root)}/")
                sub_indent = "  " * (level + 1)
                for f in files:
                    lines.append(f"{sub_indent}{f}")
            text = "\n".join(lines)
        else:
            entries = sorted(os.listdir(path))
            lines = []
            for e in entries:
                full = os.path.join(path, e)
                suffix = "/" if os.path.isdir(full) else ""
                lines.append(f"{e}{suffix}")
            text = "\n".join(lines)

        entry_count = len(lines) if lines else 0
        log.info("List files completed: path='%s' entries=%d", path, entry_count)

        return {"content": [{"type": "text", "text": text or "(empty directory)"}], "isError": False}
    except Exception as exc:
        log.error("List files failed: path='%s' error=%s", path, str(exc))
        return {
            "content": [{"type": "text", "text": f"Error listing files: {exc}"}],
            "isError": True,
        }
