# MCP Kali

> **Give your AI agent a full Kali Linux arsenal, not just a handful of wrapped CLI tools.**

A Model Context Protocol (MCP) server that runs inside a Kali Linux Docker container, giving AI agents full access to offensive security tooling through a standardized interface.

Built for real-world offensive security and CTF work, battle-tested through hundreds of Hack The Box machines, contributing to a **Top #100 global ranking** on the platform.

---

## ✨ Features at a Glance

| Feature | What It Means |
|---------|---------------|
| **Unrestricted Command Execution** | Run *any* command — not limited to a predefined list of tools |
| **Interactive PTY Sessions** | SSH, telnet, netcat, SQL shells, reverse shells — full back-and-forth interaction |
| **Background Tasks** | Fire off long-running scans without blocking the conversation |
| **HTTP Intercepting Proxy** | Capture, inspect, export, and replay HTTP traffic (built on mitmproxy) |
| **Dynamic Tool Discovery** | Find, install, and register new tools at runtime — zero restarts |
| **OpenTelemetry (OTLP) Ready** | Trace and capture every tool execution for full observability |
| **Batteries Included** | Ships with 1000+ security tools pre-installed in a Kali container |

---

## 🤔 Why MCP Kali?

MCP Kali isn't a wrapper around security tools — it's a full Kali Linux environment exposed to your AI agent through MCP primitives. Instead of one MCP function per tool, it provides building blocks that let the agent operate freely:

- **Execute any command** available in Kali, not just a predefined list
- **Open interactive sessions** for services that need back-and-forth (SSH, SQL shells, reverse shells)
- **Run scans in the background** while continuing other work
- **Intercept and replay HTTP traffic** for web testing
- **Install new tools on the fly** without restarting the server

The agent decides how to combine them, just like working in a real terminal.

---

## 🚀 Quick Start

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

---

## 📖 Documentation

- [Tools Reference](docs/tools.md) — full list of MCP tools, sessions, background tasks, proxy, and meta-tools
- [Architecture & Container](docs/architecture.md) — internals, design decisions, pre-installed packages, and OTLP tracing

---

## 🧪 Running Tests

Tests run inside Docker to match the production environment:

```bash
docker build -t mcp-kali .
docker run --rm -v $(pwd):/mcp-kali -w /mcp-kali mcp-kali \
  bash -c "pip3 install --quiet --break-system-packages pytest && python3 -m pytest tests/ -v"
```

**140 tests** covering the tool registry, JSON-RPC protocol, session management, concurrent execution, meta-tools, resources, and dynamic registration.

---

## ⚠️ Disclaimer

This project is shared for **educational and research purposes only**. It provides unrestricted command execution inside a Kali Linux container — use it responsibly and at your own risk. The authors assume no liability for misuse. Always ensure you have proper authorization before testing any target.

---

## 📄 License

MIT
