"""
mitmdump addon that captures HTTP flows to a JSONL file.

This script runs inside the mitmdump process (NOT inside the MCP server).
Each completed HTTP flow (request + response) is serialized as one JSON line.

Usage: mitmdump -s /opt/src/proxy/addon.py -p 8080 --set flow_file=/tmp/proxy_flows.jsonl
"""

import base64
import json
import time

from mitmproxy import ctx, http

FLOW_FILE = "/tmp/proxy_flows.jsonl"
MAX_BODY_SIZE = 1_048_576  # 1 MB


class FlowCapture:
    def __init__(self) -> None:
        self.flow_file = FLOW_FILE

    def load(self, loader):  # noqa: ANN001
        loader.add_option(
            name="flow_file",
            typespec=str,
            default=FLOW_FILE,
            help="Path to JSONL output file",
        )

    def configure(self, updated: set) -> None:
        if "flow_file" in updated:
            self.flow_file = ctx.options.flow_file

    def response(self, flow: http.HTTPFlow) -> None:
        """Called when a complete response has been received."""
        request = flow.request
        response = flow.response

        # Encode request body (base64 for binary safety)
        req_body_b64 = None
        if request.content and len(request.content) <= MAX_BODY_SIZE:
            req_body_b64 = base64.b64encode(request.content).decode("ascii")

        # Encode response body
        resp_body_b64 = None
        if response and response.content and len(response.content) <= MAX_BODY_SIZE:
            resp_body_b64 = base64.b64encode(response.content).decode("ascii")

        entry = {
            "timestamp": time.time(),
            "request": {
                "method": request.method,
                "url": request.pretty_url,
                "headers": dict(request.headers),
                "body_b64": req_body_b64,
                "host": request.host,
                "port": request.port,
                "scheme": request.scheme,
                "path": request.path,
            },
            "response": {
                "status_code": response.status_code if response else None,
                "headers": dict(response.headers) if response else {},
                "body_b64": resp_body_b64,
                "reason": getattr(response, "reason", None) if response else None,
            },
        }

        try:
            with open(self.flow_file, "a") as f:
                f.write(json.dumps(entry, separators=(",", ":")) + "\n")
                f.flush()
        except Exception:
            ctx.log.error(f"Failed to write flow to {self.flow_file}")


addons = [FlowCapture()]
