# 🛠️ MCP Tools Reference

## Core Execution

| Tool | Description |
|------|-------------|
| `execute_command` | Execute any shell command with optional timeout. Supports `run_in_background` for long-running scans. |
| `list_files` | List directory contents, optionally recursive. |

## Interactive Sessions (PTY)

Persistent pseudo-terminal sessions for services that require back-and-forth interaction. Each session maintains its own state and output buffer.

| Tool | Description |
|------|-------------|
| `session_create` | Start a PTY session for interactive commands (SSH, telnet, netcat, SQL clients, reverse shells). |
| `session_send` | Send input to a session and read buffered output. Send empty string to just read. |
| `session_list` | List all active sessions with metadata. |
| `session_close` | Terminate a session and clean up resources. |

- Up to **20 concurrent sessions**
- **100KB output buffer** per session (ring buffer, old output drops automatically)
- Idle sessions cleaned up after **30 minutes**
- ANSI escape codes stripped for clean LLM output

## Background Tasks

Run long-running commands without blocking the conversation.

| Tool | Description |
|------|-------------|
| `task_get_output` | Get output from a background task. Blocks by default until completion or new output. Supports `tail_lines` and `wait=false` for instant polling. |
| `task_list` | List all background tasks with status. |
| `task_stop` | Stop a running background task. |

> Start a background task by calling `execute_command` with `run_in_background: true`.

## HTTP Intercepting Proxy

Built on mitmproxy. Capture, inspect, export, and replay HTTP traffic.

| Tool | Description |
|------|-------------|
| `proxy_start` | Start the intercepting proxy on port 8080. |
| `proxy_get_flows` | List captured HTTP flows with method, URL, status code. Supports URL filtering and `last_n`. |
| `proxy_export` | Export a captured flow as raw HTTP request text (compatible with `sqlmap -r`). |
| `proxy_replay` | Replay a captured request with modified headers, body, or method. |

Route traffic through the proxy:
```bash
curl -x http://127.0.0.1:8080 http://target/path
```

## 🧩 Meta-Tools (Dynamic Tool Discovery)

The server can discover, install, and register new tools at runtime — no restart needed.

| Tool | Description |
|------|-------------|
| `system_find_tool` | Check if a tool is installed, find its path, or check if it's installable via apt. |
| `system_install_package` | Install a package via apt. Requires explicit confirmation. Rate-limited to 10/hour. Auto-registers as MCP tool. |
| `mcp_register_tool` | Register any installed CLI tool as an MCP tool with auto-detected description. Sends `tools/list_changed` notification. |

## 📋 MCP Resources

| Resource | Description |
|----------|-------------|
| `system://info` | Hostname, platform, Python version, working directory. |
| `proxy://status` | Proxy running state, PID, flow count. |
