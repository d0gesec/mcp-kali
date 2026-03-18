# Architecture

```
Claude Code <──stdio/JSON-RPC 2.0──> MCP Server <──PTY/subprocess──> Kali Tools
                                          │
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

## What's in the Container

The Docker image is based on `kalilinux/kali-rolling` and includes:

| Category | Packages |
|----------|----------|
| **Core Tools** | `kali-linux-headless` — core Kali tools without GUI |
| **OWASP Top 10** | `kali-tools-top10` — OWASP Top 10 testing tools |
| **Web Testing** | `kali-tools-web` — web application testing (includes mitmproxy) |
| **Fuzzing** | `kali-tools-fuzzing` — fuzzing frameworks |
| **Passwords** | `kali-tools-passwords` — password cracking and brute-force tools |
| **Wordlists** | `seclists` + `wordlists` — including rockyou.txt (decompressed) |
| **Active Directory** | `krb5-user`, `sshpass`, `ntpsec-ntpdate`, `faketime` |
| **Binary Analysis** | `pwntools`, `patchelf`, `qemu-user-static`, cross-arch support |
| **Recon** | `nmap`, `nuclei`, and everything in the kali metapackages |
| **Python Tools** | `pwntools`, `bloodhound`, `git-dumper`, `anthropic` |

Anything not pre-installed can be added at runtime via `system_install_package`.

## OpenTelemetry (OTLP)

Every tool call, session interaction, and background task is **instrumented with OpenTelemetry tracing**. When connected to a tracing backend (Tempo, Jaeger, etc.), you get:

- Full execution traces for every command the AI runs
- Timing data for performance analysis
- End-to-end visibility across multi-step attack chains
- Audit trail of everything that happened during a pentest or CTF

OTLP export is optional — when no collector is configured, tracing is a no-op with zero overhead.
