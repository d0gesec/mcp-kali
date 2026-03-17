#!/usr/bin/env python3
"""
MCP Server for Kali Linux Docker Container

A pure-Python Model Context Protocol (MCP) server that communicates via
stdin/stdout using JSON-RPC 2.0. Designed to run inside a Docker container
and be invoked by Claude Code via: docker exec -i <container> python3 /opt/mcp_server.py

Features:
  - Dynamic tool registration at runtime
  - Meta-tools for discovering, installing, and registering CLI tools
  - CTF tool knowledge base
  - tools/list_changed notifications
  - Execution history tracking

No external dependencies — stdlib only.
"""
import logging
import logging.handlers
import os
import signal
import sys
from typing import Any

from src.core.server import MCPServer

# Logging configuration - logs to both stderr and file
LOG_FILE = "/var/log/mcp/server.log"
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

# Create formatters
formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

# Configure root logger first
root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

# Handler for stderr (for docker exec sessions)
stderr_handler = logging.StreamHandler(sys.stderr)
stderr_handler.setFormatter(formatter)
stderr_handler.setLevel(logging.DEBUG)
root_logger.addHandler(stderr_handler)

# Handler for file (for docker logs)
file_handler = logging.handlers.RotatingFileHandler(
    LOG_FILE,
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=5,
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.DEBUG)
root_logger.addHandler(file_handler)

log = logging.getLogger("pownie-kali-mcp")


def main() -> None:
    """Entry point for the MCP server."""
    log.info("MCP Server lifecycle: status=initializing")

    try:
        server = MCPServer()

        def _signal_handler(sig: int, _: Any) -> None:
            log.warning("MCP Server signal received: signal=%d action=shutting_down", sig)
            server.shutdown()

        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)

        log.info("MCP Server lifecycle: status=ready")
        server.run()

    except KeyboardInterrupt:
        log.info("MCP Server lifecycle: status=shutdown reason=keyboard_interrupt")
    except Exception as exc:
        log.critical("MCP Server lifecycle: status=crashed error=%s", str(exc), exc_info=True)
        sys.exit(1)
    finally:
        log.info("MCP Server lifecycle: status=terminated")


if __name__ == "__main__":
    main()
