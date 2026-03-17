"""
Built-in resource handlers.
"""
import json
import os
import platform


def handle_system_info() -> dict:
    """Return system information as a resource."""
    info = json.dumps(
        {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "cwd": os.getcwd(),
        },
        indent=2,
    )
    return {
        "contents": [
            {
                "uri": "system://info",
                "mimeType": "application/json",
                "text": info,
            }
        ],
    }
