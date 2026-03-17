"""
Meta-tool handlers for discovering, installing, and registering CLI tools.
"""
import json
import logging
import re
import shlex
import sys
from typing import TYPE_CHECKING, Callable

from ..config.constants import MAX_INSTALLS_PER_HOUR
from ..config.schemas import GENERIC_CLI_SCHEMA
from ..tools.base import create_generic_tool_handler
from ..utils.rate_limiter import install_limiter
from ..utils.subprocess import execute_subprocess
from ..utils.validation import validate_package_name

if TYPE_CHECKING:
    from ..core.server import MCPServer

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")


def handle_system_find_tool(args: dict) -> dict:
    """Check if a command-line tool is available on the system."""
    tool_name = args.get("tool_name")
    if not tool_name or not isinstance(tool_name, str):
        log.warning("Find tool failed: reason=missing_tool_name")
        return {
            "content": [{"type": "text", "text": "Missing required parameter: tool_name"}],
            "isError": True,
        }

    log.info("Finding tool: tool_name='%s'", tool_name)

    # Sanitise: only allow simple tool names
    if not re.match(r"^[a-zA-Z0-9_.-]+$", tool_name):
        log.warning("Find tool failed: tool_name='%s' reason=invalid_name", tool_name)
        return {
            "content": [{"type": "text", "text": f"Invalid tool name: {tool_name}"}],
            "isError": True,
        }

    # Check if installed
    which_result = execute_subprocess(f"command -v {shlex.quote(tool_name)}", timeout=10)
    if which_result["exit_code"] == 0 and which_result["stdout"].strip():
        tool_path = which_result["stdout"].strip()
        log.info("Tool found: tool_name='%s' path='%s'", tool_name, tool_path)
        result_data = {
            "available": True,
            "path": tool_path,
        }
        return {
            "content": [{"type": "text", "text": json.dumps(result_data, indent=2)}],
            "isError": False,
        }

    log.info("Tool not found, checking installability: tool_name='%s'", tool_name)

    # Not installed — check if installable via apt
    apt_result = execute_subprocess(
        f"apt-cache search --names-only '^{re.escape(tool_name)}$'", timeout=30
    )
    if apt_result["exit_code"] == 0 and apt_result["stdout"].strip():
        pkg_line = apt_result["stdout"].strip().split("\n")[0]
        pkg_name = pkg_line.split(" - ")[0].strip() if " - " in pkg_line else tool_name
        log.info("Tool installable via apt: tool_name='%s' package='%s'", tool_name, pkg_name)
        result_data = {
            "available": False,
            "installable": True,
            "package_name": pkg_name,
            "method": "apt",
        }
    else:
        # Also try a broader search
        broad = execute_subprocess(
            f"apt-cache search {shlex.quote(tool_name)} 2>/dev/null | head -5", timeout=30
        )
        suggestions = broad["stdout"].strip() if broad["exit_code"] == 0 else ""
        log.info("Tool not installable: tool_name='%s' has_suggestions=%s",
                 tool_name, bool(suggestions))
        result_data = {
            "available": False,
            "installable": False,
            "suggestions": suggestions or "No packages found",
        }

    return {
        "content": [{"type": "text", "text": json.dumps(result_data, indent=2)}],
        "isError": False,
    }


def make_install_handler(server: "MCPServer") -> Callable[[dict], dict]:
    """Create the system_install_package handler bound to a server instance."""

    def handle_system_install_package(args: dict) -> dict:
        """Install a package using apt and optionally register as MCP tool."""
        package_name = args.get("package_name", "")
        confirm = args.get("confirm", False)

        # Validation
        err = validate_package_name(package_name)
        if err:
            return {
                "content": [{"type": "text", "text": json.dumps({"success": False, "error": err})}],
                "isError": True,
            }
        if confirm is not True:
            return {
                "content": [{"type": "text", "text": json.dumps({
                    "success": False,
                    "error": "confirm must be true — explicit confirmation required for safety",
                })}],
                "isError": True,
            }

        # Rate limit
        if not install_limiter.check():
            return {
                "content": [{"type": "text", "text": json.dumps({
                    "success": False,
                    "error": f"Rate limit exceeded: max {MAX_INSTALLS_PER_HOUR} installs per hour",
                })}],
                "isError": True,
            }

        log.info("Package installation started: package='%s'", package_name)
        result = execute_subprocess(
            f"apt-get update -qq && apt-get install -y {shlex.quote(package_name)}",
            timeout=600,
        )
        install_limiter.record()

        if result["exit_code"] != 0:
            log.error("Package installation failed: package='%s' exit_code=%d",
                      package_name, result["exit_code"])
            return {
                "content": [{"type": "text", "text": json.dumps({
                    "success": False,
                    "error": "Installation failed",
                    "stderr": result["stderr"][-2000:],
                }, indent=2)}],
                "isError": True,
            }

        log.info("Package installation succeeded: package='%s'", package_name)

        # Try to auto-register the installed tool
        mcp_registered = False
        # Check if a binary with the same name exists now
        which = execute_subprocess(f"command -v {shlex.quote(package_name)}", timeout=5)
        if which["exit_code"] == 0 and which["stdout"].strip():
            desc = f"Installed package: {package_name}"
            # Try to get a short description from dpkg
            dpkg = execute_subprocess(
                f"dpkg -s {shlex.quote(package_name)} 2>/dev/null | grep '^Description:' | head -1",
                timeout=5,
            )
            if dpkg["exit_code"] == 0 and dpkg["stdout"].strip():
                desc = dpkg["stdout"].strip().removeprefix("Description:").strip()

            log.info("Auto-registering tool as MCP: tool='%s'", package_name)
            reg = server.tools.add_tool(
                name=package_name,
                description=desc,
                input_schema=GENERIC_CLI_SCHEMA,
                handler=create_generic_tool_handler(package_name),
                category="installed",
                install_method="apt",
            )
            mcp_registered = reg["success"]
            if mcp_registered:
                log.info("MCP tool registration succeeded: tool='%s'", package_name)
            else:
                log.warning("MCP tool registration failed: tool='%s'", package_name)

        return {
            "content": [{"type": "text", "text": json.dumps({
                "success": True,
                "package": package_name,
                "mcp_tool_registered": mcp_registered,
                "output": result["stdout"][-2000:],
            }, indent=2)}],
            "isError": False,
        }

    return handle_system_install_package


def make_register_handler(server: "MCPServer") -> Callable[[dict], dict]:
    """Create the mcp_register_tool handler bound to a server instance."""

    def handle_mcp_register_tool(args: dict) -> dict:
        """Register a command-line tool as an MCP tool."""
        tool_name = args.get("tool_name", "")
        tool_description = args.get("tool_description", "")
        tool_category = args.get("tool_category", "general")

        if not tool_name or not isinstance(tool_name, str):
            log.warning("MCP tool registration failed: reason=missing_tool_name")
            return {
                "content": [{"type": "text", "text": json.dumps({
                    "success": False, "error": "tool_name is required",
                })}],
                "isError": True,
            }

        log.info("MCP tool registration started: tool='%s' category='%s'",
                 tool_name, tool_category)

        # Verify the tool actually exists on the system
        which = execute_subprocess(f"command -v {shlex.quote(tool_name)}", timeout=5)
        if which["exit_code"] != 0:
            log.warning("MCP tool registration failed: tool='%s' reason=not_found_in_path",
                        tool_name)
            return {
                "content": [{"type": "text", "text": json.dumps({
                    "success": False,
                    "error": f"Tool '{tool_name}' not found on system (not in PATH)",
                })}],
                "isError": True,
            }

        # Try to get description from man page / dpkg if not provided
        if not tool_description:
            log.debug("Auto-detecting description for tool: tool='%s'", tool_name)
            dpkg = execute_subprocess(
                f"dpkg -s {shlex.quote(tool_name)} 2>/dev/null | grep '^Description:' | head -1",
                timeout=5,
            )
            if dpkg["exit_code"] == 0 and dpkg["stdout"].strip():
                tool_description = dpkg["stdout"].strip().removeprefix("Description:").strip()
            else:
                # Try --help first line
                help_result = execute_subprocess(
                    f"{shlex.quote(tool_name)} --help 2>&1 | head -1", timeout=5
                )
                tool_description = (
                    help_result["stdout"].strip()[:200]
                    if help_result["stdout"].strip()
                    else f"CLI tool: {tool_name}"
                )

        reg = server.tools.add_tool(
            name=tool_name,
            description=tool_description,
            input_schema=GENERIC_CLI_SCHEMA,
            handler=create_generic_tool_handler(tool_name),
            category=tool_category,
            install_method="manual",
        )

        if not reg["success"]:
            log.error("MCP tool registration failed: tool='%s' error='%s'",
                      tool_name, reg.get("error"))
            return {
                "content": [{"type": "text", "text": json.dumps(reg)}],
                "isError": True,
            }

        log.info("MCP tool registration succeeded: tool='%s' category='%s' description='%s'",
                 tool_name, tool_category, tool_description[:100])

        return {
            "content": [{"type": "text", "text": json.dumps({
                "success": True,
                "tool_name": tool_name,
                "description": tool_description,
                "category": tool_category,
                "mcp_available": True,
            }, indent=2)}],
            "isError": False,
        }

    return handle_mcp_register_tool
