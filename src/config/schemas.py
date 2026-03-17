"""
JSON schemas for tool input validation.
"""

# Generic input schema for wrapped CLI tools
GENERIC_CLI_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "target": {
            "type": "string",
            "description": "Primary target (IP, URL, file path)",
        },
        "flags": {
            "type": "string",
            "description": "Command-line flags (e.g. '-sV -p 80,443')",
        },
        "args": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Additional positional arguments",
        },
        "timeout": {
            "type": "integer",
            "description": "Timeout in seconds (default 300)",
        },
    },
}

# Session management schemas
SESSION_CREATE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "command": {
            "type": "string",
            "description": "Shell command to run in PTY session (e.g., 'telnet host', 'nc -v ip port')",
        },
        "name": {
            "type": "string",
            "description": "Optional friendly name for the session",
        },
        "timeout": {
            "type": "integer",
            "description": "Initial command timeout in seconds (default 300)",
        },
    },
    "required": ["command"],
}

SESSION_SEND_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Session ID from session_create",
        },
        "input": {
            "type": "string",
            "description": "Input to send to the session (empty string to just read output)",
        },
        "read_timeout": {
            "type": "integer",
            "description": "How long to wait for output in seconds (default 1)",
        },
    },
    "required": ["session_id"],
}

SESSION_LIST_SCHEMA: dict = {
    "type": "object",
    "properties": {},
}

SESSION_CLOSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "description": "Session ID to close",
        },
    },
    "required": ["session_id"],
}

# Background task management schemas
TASK_GET_OUTPUT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "Task ID from execute_command run_in_background",
        },
        "tail_lines": {
            "type": "integer",
            "description": "Optional: return only last N lines of output",
        },
        "wait": {
            "type": "boolean",
            "description": "Block until task completes or new output appears (default true). Set false for instant poll.",
            "default": True,
        },
        "timeout": {
            "type": "integer",
            "description": "Max seconds to wait when wait=true (default 30, max 120)",
            "default": 30,
        },
    },
    "required": ["task_id"],
}

TASK_LIST_SCHEMA: dict = {
    "type": "object",
    "properties": {},
}

TASK_STOP_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "task_id": {
            "type": "string",
            "description": "Task ID to stop",
        },
    },
    "required": ["task_id"],
}

# Proxy tool schemas

PROXY_START_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "clear_flows": {
            "type": "boolean",
            "description": "Clear previously captured flows on start (default: true)",
        },
    },
}

PROXY_GET_FLOWS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "filter_url": {
            "type": "string",
            "description": "Only show flows whose URL contains this substring",
        },
        "last_n": {
            "type": "integer",
            "description": "Only show the last N flows (default: all)",
        },
    },
}

PROXY_EXPORT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "index": {
            "type": "integer",
            "description": "Flow index number (from proxy_get_flows output)",
        },
        "filter_url": {
            "type": "string",
            "description": "Export the last flow matching this URL substring (alternative to index)",
        },
    },
}

PROXY_REPLAY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "index": {
            "type": "integer",
            "description": "Flow index number to replay (from proxy_get_flows output)",
        },
        "filter_url": {
            "type": "string",
            "description": "Replay the last flow matching this URL substring (alternative to index)",
        },
        "modify_headers": {
            "type": "object",
            "description": "Headers to add/override in the replayed request (key-value pairs)",
            "additionalProperties": {"type": "string"},
        },
        "modify_body": {
            "type": "string",
            "description": "Replace the request body with this string",
        },
        "modify_method": {
            "type": "string",
            "description": "Override the HTTP method (GET, POST, PUT, etc.)",
        },
    },
}
