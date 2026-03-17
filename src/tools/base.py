"""
Base tool functionality and generic CLI tool wrapper.
"""
import logging
import shlex
import sys
from typing import Callable

from ..config.constants import DEFAULT_COMMAND_TIMEOUT
from ..utils.subprocess import execute_subprocess

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")


def create_generic_tool_handler(tool_name: str) -> Callable[[dict], dict]:
    """Generate a handler that wraps any CLI tool.

    The handler accepts:
      target  (str, optional)  — primary target (IP, URL, file)
      flags   (str, optional)  — command-line flags as a string
      args    (list, optional) — additional positional arguments
      timeout (int, optional)  — execution timeout in seconds
    """

    def handler(arguments: dict) -> dict:
        command_parts = [tool_name]

        flags = arguments.get("flags")
        if flags and isinstance(flags, str):
            command_parts.extend(shlex.split(flags))

        target = arguments.get("target")
        if target and isinstance(target, str):
            command_parts.append(target)

        extra = arguments.get("args")
        if extra and isinstance(extra, list):
            command_parts.extend(str(a) for a in extra)

        timeout = arguments.get("timeout", DEFAULT_COMMAND_TIMEOUT)
        if not isinstance(timeout, int) or timeout < 1:
            timeout = DEFAULT_COMMAND_TIMEOUT

        cmd_str = " ".join(shlex.quote(p) for p in command_parts)

        log.info("Executing generic CLI tool: tool='%s' cmd='%s' timeout=%d",
                 tool_name, cmd_str, timeout)

        result = execute_subprocess(cmd_str, timeout=timeout)

        log.info("Generic CLI tool completed: tool='%s' exit_code=%d timed_out=%s",
                 tool_name, result['exit_code'], result['timed_out'])

        text = (
            f"Command: {cmd_str}\n\n"
            f"Exit Code: {result['exit_code']}\n\n"
            f"STDOUT:\n{result['stdout']}\n\n"
            f"STDERR:\n{result['stderr']}"
        )
        if result["timed_out"]:
            text += "\n\n(command timed out)"
        return {
            "content": [{"type": "text", "text": text}],
            "isError": result["exit_code"] != 0,
        }

    return handler
