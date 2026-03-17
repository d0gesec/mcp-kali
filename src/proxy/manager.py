"""
Proxy lifecycle manager using mitmdump as a subprocess.

Manages a mitmdump intercepting proxy for capturing and replaying HTTP traffic.
Designed for the Kali MCP server — curl routes through the proxy natively.
"""

import base64
import json
import logging
import os
import signal
import socket
import subprocess
import time
from typing import Any

from ..config.constants import (
    PROXY_ADDON_SCRIPT,
    PROXY_FLOW_FILE,
    PROXY_HOST,
    PROXY_PORT,
    PROXY_STARTUP_TIMEOUT,
    SERVER_NAME,
)

log = logging.getLogger(SERVER_NAME)


class ProxyManager:
    """Manages a mitmdump intercepting proxy subprocess."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._flow_file = PROXY_FLOW_FILE
        self._port = PROXY_PORT

    @property
    def is_running(self) -> bool:
        if self._process is None:
            return False
        return self._process.poll() is None

    @property
    def proxy_url(self) -> str:
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> dict[str, Any]:
        """Start mitmdump subprocess. Returns status dict."""
        if self.is_running:
            return {
                "status": "already_running",
                "pid": self._process.pid,
                "proxy_url": self.proxy_url,
                "flow_file": self._flow_file,
            }

        # Clear old flow file
        if os.path.exists(self._flow_file):
            os.remove(self._flow_file)

        cmd = [
            "mitmdump",
            "--listen-host", PROXY_HOST,
            "--listen-port", str(self._port),
            "--set", f"flow_file={self._flow_file}",
            "-s", PROXY_ADDON_SCRIPT,
            "--ssl-insecure",
            "-q",
        ]

        log.info("Proxy starting: cmd=%s", " ".join(cmd))

        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            preexec_fn=os.setsid,
        )

        # Wait for mitmdump to be ready by polling the port
        deadline = time.time() + PROXY_STARTUP_TIMEOUT
        started = False
        while time.time() < deadline:
            if self._process.poll() is not None:
                stderr_output = self._process.stderr.read().decode(errors="replace")
                log.error("Proxy failed to start: %s", stderr_output)
                self._process = None
                return {
                    "status": "failed",
                    "error": f"mitmdump exited: {stderr_output[:500]}",
                }
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex(("127.0.0.1", self._port))
                sock.close()
                if result == 0:
                    started = True
                    break
            except Exception:
                pass
            time.sleep(0.3)

        if not started:
            log.warning("Proxy port not confirmed listening, but process is alive (pid=%d)", self._process.pid)

        log.info("Proxy started: pid=%d port=%d", self._process.pid, self._port)

        return {
            "status": "started",
            "pid": self._process.pid,
            "proxy_url": self.proxy_url,
            "flow_file": self._flow_file,
        }

    def stop(self) -> None:
        """Stop the mitmdump subprocess."""
        if self._process is not None:
            try:
                os.killpg(os.getpgid(self._process.pid), signal.SIGTERM)
                self._process.wait(timeout=5)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None
        log.info("Proxy stopped")

    def get_flows(
        self,
        filter_url: str | None = None,
        last_n: int | None = None,
    ) -> list[dict]:
        """Read captured flows from the JSONL file."""
        if not os.path.exists(self._flow_file):
            return []

        flows = []
        with open(self._flow_file, "r") as f:
            for line_num, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    flow = json.loads(line)
                    flow["_index"] = line_num
                    if filter_url:
                        url = flow.get("request", {}).get("url", "")
                        if filter_url.lower() not in url.lower():
                            continue
                    flows.append(flow)
                except json.JSONDecodeError:
                    continue

        if last_n is not None and last_n > 0:
            flows = flows[-last_n:]

        return flows

    def export_flow_raw_http(self, flow: dict) -> str:
        """Export a flow as raw HTTP request text (sqlmap -r compatible)."""
        req = flow.get("request", {})
        method = req.get("method", "GET")
        path = req.get("path", "/")
        host = req.get("host", "")
        headers = req.get("headers", {})

        lines = [f"{method} {path} HTTP/1.1"]

        # Ensure Host header is present
        if "host" not in {k.lower() for k in headers}:
            lines.append(f"Host: {host}")

        for key, value in headers.items():
            lines.append(f"{key}: {value}")

        # Decode and append body if present
        body_b64 = req.get("body_b64")
        body_text = ""
        if body_b64:
            try:
                body_text = base64.b64decode(body_b64).decode("utf-8", errors="replace")
            except Exception:
                body_text = ""

        if body_text:
            lines.append("")
            lines.append(body_text)
        else:
            lines.append("")

        return "\r\n".join(lines)

    def replay_flow(
        self,
        flow: dict,
        modify_headers: dict | None = None,
        modify_body: str | None = None,
        modify_method: str | None = None,
    ) -> dict:
        """Replay a captured request using the requests library (bypasses proxy)."""
        import requests as req_lib

        req = flow.get("request", {})
        method = modify_method or req.get("method", "GET")
        url = req.get("url", "")
        headers = dict(req.get("headers", {}))

        if modify_headers:
            headers.update(modify_headers)

        body = None
        body_b64 = req.get("body_b64")
        if modify_body is not None:
            body = modify_body
        elif body_b64:
            try:
                body = base64.b64decode(body_b64).decode("utf-8", errors="replace")
            except Exception:
                body = None

        try:
            resp = req_lib.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                verify=False,
                timeout=30,
                allow_redirects=False,
            )
            return {
                "status_code": resp.status_code,
                "headers": dict(resp.headers),
                "body": resp.text[:10000],
                "url": url,
                "method": method,
            }
        except Exception as exc:
            return {"error": str(exc), "url": url, "method": method}

    def get_status(self) -> dict:
        """Return proxy status information."""
        flow_count = 0
        if os.path.exists(self._flow_file):
            with open(self._flow_file, "r") as f:
                flow_count = sum(1 for line in f if line.strip())

        return {
            "running": self.is_running,
            "pid": self._process.pid if self._process else None,
            "proxy_url": self.proxy_url if self.is_running else None,
            "flow_file": self._flow_file,
            "flow_count": flow_count,
            "port": self._port,
        }

    def shutdown(self) -> None:
        """Full cleanup -- stop proxy and remove flow file."""
        self.stop()
        if os.path.exists(self._flow_file):
            try:
                os.remove(self._flow_file)
            except Exception:
                pass
        log.info("ProxyManager shutdown complete")
