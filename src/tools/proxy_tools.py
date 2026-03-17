"""
Proxy tool handlers for the Kali MCP server.

4 tools for intercepting proxy operations: start, get flows, export, replay.
Uses the make_xxx_handlers() factory pattern.

Unlike the browser version, proxy_start does NOT reconfigure a browser —
it simply starts mitmdump. Use curl -x http://127.0.0.1:8080 to route traffic.
"""

import base64
import json
import logging
from typing import TYPE_CHECKING, Callable

from ..config.constants import SERVER_NAME

if TYPE_CHECKING:
    from ..proxy.manager import ProxyManager

log = logging.getLogger(SERVER_NAME)


def _ok(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": False}


def _err(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}], "isError": True}


def make_proxy_handlers(
    pm: "ProxyManager",
) -> dict[str, Callable[[dict], dict]]:
    """Create proxy tool handlers bound to ProxyManager."""

    def handle_proxy_start(args: dict) -> dict:
        """Start the intercepting proxy."""
        try:
            result = pm.start()
            status = result.get("status")

            if status == "failed":
                return _err(f"Proxy failed to start: {result.get('error', 'unknown')}")

            lines = [
                f"Proxy status: {status}",
                f"Proxy URL: {result.get('proxy_url')}",
                f"PID: {result.get('pid')}",
                f"Flow file: {result.get('flow_file')}",
                "",
                "Route traffic through the proxy with:",
                "  curl -x http://127.0.0.1:8080 http://target/path",
                "  curl -x http://127.0.0.1:8080 -k https://target/path",
                "",
                "Use proxy_get_flows to inspect captured requests.",
            ]
            return _ok("\n".join(lines))
        except Exception as exc:
            log.error("proxy_start failed: %s", exc, exc_info=True)
            return _err(f"proxy_start error: {exc}")

    def handle_proxy_get_flows(args: dict) -> dict:
        """Get captured HTTP flows."""
        if not pm.is_running:
            return _err("Proxy is not running. Call proxy_start first.")

        try:
            filter_url = args.get("filter_url")
            last_n = args.get("last_n")
            flows = pm.get_flows(filter_url=filter_url, last_n=last_n)

            if not flows:
                msg = "(no flows captured yet)"
                if filter_url:
                    msg += f" matching '{filter_url}'"
                return _ok(msg)

            lines = []
            header = f"Captured flows: {len(flows)}"
            if filter_url:
                header += f" (filter: '{filter_url}')"
            lines.append(header)
            lines.append("-" * 40)

            for flow in flows:
                idx = flow.get("_index", "?")
                req = flow.get("request", {})
                resp = flow.get("response", {})
                method = req.get("method", "?")
                url = req.get("url", "?")
                status = resp.get("status_code", "?")
                line = f"[{idx}] {method} {url} -> {status}"

                req_body = req.get("body_b64")
                if req_body:
                    try:
                        body_len = len(base64.b64decode(req_body))
                        line += f" (req: {body_len}B)"
                    except Exception:
                        pass

                lines.append(line)

            return _ok("\n".join(lines))
        except Exception as exc:
            log.error("proxy_get_flows failed: %s", exc, exc_info=True)
            return _err(f"proxy_get_flows error: {exc}")

    def handle_proxy_export(args: dict) -> dict:
        """Export a flow as raw HTTP for sqlmap -r."""
        if not pm.is_running:
            return _err("Proxy is not running. Call proxy_start first.")

        try:
            index = args.get("index")
            filter_url = args.get("filter_url")

            if index is None and not filter_url:
                return _err("Must provide either 'index' or 'filter_url'")

            flows = pm.get_flows(filter_url=filter_url)
            if not flows:
                return _err("No matching flows found")

            target_flow = None
            if index is not None:
                for flow in flows:
                    if flow.get("_index") == index:
                        target_flow = flow
                        break
                if target_flow is None:
                    return _err(f"No flow found at index {index}")
            else:
                target_flow = flows[-1]

            raw_http = pm.export_flow_raw_http(target_flow)
            req = target_flow.get("request", {})

            lines = [
                f"# Raw HTTP request (flow index {target_flow.get('_index')})",
                f"# {req.get('method')} {req.get('url')}",
                f"# Save to file, then: sqlmap -r /tmp/request.txt",
                "",
                raw_http,
            ]
            return _ok("\n".join(lines))
        except Exception as exc:
            log.error("proxy_export failed: %s", exc, exc_info=True)
            return _err(f"proxy_export error: {exc}")

    def handle_proxy_replay(args: dict) -> dict:
        """Replay a captured request with optional modifications."""
        if not pm.is_running:
            return _err("Proxy is not running. Call proxy_start first.")

        try:
            index = args.get("index")
            filter_url = args.get("filter_url")

            if index is None and not filter_url:
                return _err("Must provide either 'index' or 'filter_url'")

            flows = pm.get_flows(filter_url=filter_url)
            if not flows:
                return _err("No matching flows found")

            target_flow = None
            if index is not None:
                for flow in flows:
                    if flow.get("_index") == index:
                        target_flow = flow
                        break
                if target_flow is None:
                    return _err(f"No flow found at index {index}")
            else:
                target_flow = flows[-1]

            result = pm.replay_flow(
                target_flow,
                modify_headers=args.get("modify_headers"),
                modify_body=args.get("modify_body"),
                modify_method=args.get("modify_method"),
            )

            if "error" in result:
                return _err(f"Replay failed: {result['error']}")

            lines = [
                f"Replay: {result.get('method')} {result.get('url')}",
                f"Status: {result.get('status_code')}",
                "",
                "Response Headers:",
                json.dumps(result.get("headers", {}), indent=2),
                "",
                "Response Body:",
                result.get("body", "(empty)"),
            ]
            return _ok("\n".join(lines))
        except Exception as exc:
            log.error("proxy_replay failed: %s", exc, exc_info=True)
            return _err(f"proxy_replay error: {exc}")

    return {
        "proxy_start": handle_proxy_start,
        "proxy_get_flows": handle_proxy_get_flows,
        "proxy_export": handle_proxy_export,
        "proxy_replay": handle_proxy_replay,
    }
