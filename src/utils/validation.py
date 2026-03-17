"""
Validation utilities for package names and tool definitions.
"""
import re

from ..config.constants import PACKAGE_NAME_RE


def validate_package_name(name: str) -> str | None:
    """Return an error message if the package name is invalid, else None."""
    if not name or not isinstance(name, str):
        return "Package name must be a non-empty string"
    if len(name) > 128:
        return "Package name too long (max 128 characters)"
    if not PACKAGE_NAME_RE.match(name):
        return (
            f"Invalid package name '{name}': "
            "only alphanumeric, dash, underscore, dot, and plus allowed"
        )
    return None


def validate_tool_definition(name: str, description: str, input_schema: dict) -> str | None:
    """Return an error message if the tool definition is invalid, else None."""
    if not name or not isinstance(name, str):
        return "Tool name must be a non-empty string"
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return f"Invalid tool name '{name}': only alphanumeric, dash, underscore allowed"
    if not description or not isinstance(description, str):
        return "Tool description must be a non-empty string"
    if not isinstance(input_schema, dict):
        return "inputSchema must be a JSON object"
    return None
