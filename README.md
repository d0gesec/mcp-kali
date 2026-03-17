# MCP Kali

A Model Context Protocol (MCP) server that runs inside a Kali Linux Docker container, giving AI agents full access to offensive security tooling through a standardized interface.

Built for real-world offensive security and CTF work, not toy wrappers around individual tools. This server was developed and battle-tested through hundreds of Hack The Box machines, contributing to a **#134 global ranking** on the platform.

## Why This Exists

Most MCP security servers wrap individual tools (run nmap, run gobuster, etc). That approach breaks down the moment you need to:

- Chain exploit stages that depend on previous output
- Interact with services that require back-and-forth (telnet, SSH, netcat, SQL shells)
- Run long scans in the background while doing other work
- Intercept and replay HTTP traffic for injection testing
- Install and use a tool that wasn't pre-configured

MCP Kali solves this by providing **primitives** — command execution, interactive sessions, background tasks, HTTP interception, and dynamic tool registration — inside a fully-loaded Kali container. The AI agent decides how to combine them.

## Quick Start

### 1. Build the Docker image

```bash
docker build -t mcp-kali .
```

### 2. Run the container

```bash
docker run -d --name mcp-kali --privileged mcp-kali
```

### 3. Configure Claude Code

Add to your `.mcp.json`:

```json
{
  "mcpServers": {
    "kali": {
      "type": "stdio",
      "command": "docker",
      "args": ["exec", "-i", "mcp-kali", "python3", "/opt/mcp_server.py"]
    }
  }
}
```

## MCP Tools

### Core

| Tool | Description |
|------|-------------|
| `execute_command` | Execute any shell command with optional timeout. Supports `run_in_background` for long-running scans. |
| `list_files` | List directory contents, optionally recursive. |

### Interactive Sessions (PTY)

Persistent pseudo-terminal sessions for services that require back-and-forth interaction. Each session maintains its own state and output buffer.

| Tool | Description |
|------|-------------|
| `session_create` | Start a PTY session for interactive commands (SSH, telnet, netcat, SQL clients, reverse shells). |
| `session_send` | Send input to a session and read buffered output. Send empty string to just read. |
| `session_list` | List all active sessions with metadata. |
| `session_close` | Terminate a session and clean up resources. |

Up to 20 concurrent sessions. 100KB output buffer per session (ring buffer, old output drops automatically). Idle sessions are cleaned up after 30 minutes. ANSI escape codes are stripped for clean LLM output.

### Background Tasks

Run long-running commands without blocking the conversation.

| Tool | Description |
|------|-------------|
| `task_get_output` | Get output from a background task. Blocks by default until completion or new output. Supports `tail_lines` and `wait=false` for instant polling. |
| `task_list` | List all background tasks with status. |
| `task_stop` | Stop a running background task. |

Start a background task by calling `execute_command` with `run_in_background: true`.

### HTTP Intercepting Proxy

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

### Meta-Tools (Dynamic Tool Discovery)

The server can discover, install, and register new tools at runtime — no restart needed.

| Tool | Description |
|------|-------------|
| `system_find_tool` | Check if a tool is installed, find its path, or check if it's installable via apt. |
| `system_install_package` | Install a package via apt. Requires explicit confirmation. Rate-limited to 10/hour. Auto-registers as MCP tool. |
| `mcp_register_tool` | Register any installed CLI tool as an MCP tool with auto-detected description. Sends `tools/list_changed` notification. |

### MCP Resources

| Resource | Description |
|----------|-------------|
| `system://info` | Hostname, platform, Python version, working directory. |
| `proxy://status` | Proxy running state, PID, flow count. |

## Architecture

```
Claude Code <--stdio/JSON-RPC 2.0--> MCP Server <--PTY/subprocess--> Kali Tools
                                          |
                                          ├── ToolRegistry (dynamic, with history tracking)
                                          ├── SessionManager (PTY sessions with ring buffers)
                                          ├── BackgroundTaskManager (async execution)
                                          ├── ProxyManager (mitmproxy subprocess)
                                          └── OpenTelemetry tracing (optional)
```

- **Pure Python / stdlib** — no framework dependencies for the core server
- **JSON-RPC 2.0** over stdin/stdout (MCP protocol `2024-11-05`)
- **Thread-safe** registries with global locks
- **Non-blocking I/O** via `select()` for PTY sessions
- **Ring buffer output** — deque-based with automatic FIFO eviction
- **Graceful shutdown** — signal handlers + cleanup threads
- **OpenTelemetry tracing** — optional, connects to Tempo when available

## What's in the Container

The Docker image is based on `kalilinux/kali-rolling` and includes:

- **kali-linux-headless** — core Kali tools without GUI
- **kali-tools-top10** — OWASP Top 10 testing tools
- **kali-tools-web** — web application testing (includes mitmproxy)
- **kali-tools-fuzzing** — fuzzing frameworks
- **kali-tools-passwords** — password cracking and brute-force tools
- **seclists + wordlists** — including rockyou.txt (decompressed)
- **AD/Kerberos** — krb5-user, sshpass, ntpsec-ntpdate, faketime
- **Binary analysis** — pwntools, patchelf, qemu-user-static, binutils-x86-64-linux-gnu, libc6:amd64 (cross-arch on ARM)
- **Recon** — nmap, nuclei, and everything else in the kali metapackages
- **Python tools** — pwntools, bloodhound, git-dumper, anthropic

Anything not pre-installed can be added at runtime via `system_install_package`.

## Running Tests

Tests run inside Docker to match the production environment:

```bash
docker build -t mcp-kali .
docker run --rm -v $(pwd):/mcp-kali -w /mcp-kali mcp-kali \
  bash -c "pip3 install --quiet --break-system-packages pytest && python3 -m pytest tests/ -v"
```

140 tests covering the tool registry, JSON-RPC protocol, session management, concurrent execution, meta-tools, resources, and dynamic registration.

## License

MIT
