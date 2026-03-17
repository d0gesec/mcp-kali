#!/usr/bin/env python3
"""
Interactive REPL for manual MCP server testing.

Starts the MCP server as a subprocess and provides a command-line interface
to send JSON-RPC messages and inspect responses.

Usage:
    # Local:
    python3 tests/repl.py

    # Against Docker container:
    python3 tests/repl.py --docker pownie-kali

Built-in commands:
    init          Send initialize + initialized
    ping          Send ping
    tools         Send tools/list
    resources     Send resources/list
    call <tool> <json>   Send tools/call (e.g. call execute_command {"command":"whoami"})
    read <uri>    Send resources/read (e.g. read system://info)
    raw <json>    Send raw JSON-RPC message
    help          Show this help
    quit / exit   Shutdown server and exit
"""

import argparse
import json
import readline  # enables arrow keys / history in input()
import subprocess
import sys
from pathlib import Path


class MCPRepl:
    def __init__(self, cmd: list[str]):
        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._next_id = 1

    def _get_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def send(self, message: dict) -> dict | None:
        line = json.dumps(message, separators=(",", ":")) + "\n"
        self.proc.stdin.write(line)
        self.proc.stdin.flush()

        if "id" not in message:
            return None

        raw = self.proc.stdout.readline()
        if not raw:
            print("  [no response — server may have closed]")
            return None
        return json.loads(raw)

    def print_response(self, resp: dict | None) -> None:
        if resp is None:
            print("  (no response — notification)")
            return
        print(json.dumps(resp, indent=2))

    def cmd_init(self) -> None:
        resp = self.send({
            "jsonrpc": "2.0",
            "id": self._get_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "repl", "version": "0.1"},
            },
        })
        self.print_response(resp)
        # Send initialized notification
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        print("  (sent initialized notification)")

    def cmd_ping(self) -> None:
        resp = self.send({"jsonrpc": "2.0", "id": self._get_id(), "method": "ping"})
        self.print_response(resp)

    def cmd_tools(self) -> None:
        resp = self.send({"jsonrpc": "2.0", "id": self._get_id(), "method": "tools/list"})
        self.print_response(resp)

    def cmd_resources(self) -> None:
        resp = self.send({"jsonrpc": "2.0", "id": self._get_id(), "method": "resources/list"})
        self.print_response(resp)

    def cmd_call(self, rest: str) -> None:
        parts = rest.strip().split(None, 1)
        if not parts:
            print("Usage: call <tool_name> [arguments_json]")
            return
        name = parts[0]
        arguments = {}
        if len(parts) > 1:
            try:
                arguments = json.loads(parts[1])
            except json.JSONDecodeError as e:
                print(f"Invalid JSON arguments: {e}")
                return

        resp = self.send({
            "jsonrpc": "2.0",
            "id": self._get_id(),
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        })
        self.print_response(resp)

    def cmd_read(self, uri: str) -> None:
        uri = uri.strip()
        if not uri:
            print("Usage: read <uri>")
            return
        resp = self.send({
            "jsonrpc": "2.0",
            "id": self._get_id(),
            "method": "resources/read",
            "params": {"uri": uri},
        })
        self.print_response(resp)

    def cmd_raw(self, raw_json: str) -> None:
        try:
            msg = json.loads(raw_json)
        except json.JSONDecodeError as e:
            print(f"Invalid JSON: {e}")
            return
        resp = self.send(msg)
        self.print_response(resp)

    def close(self) -> None:
        self.proc.stdin.close()
        self.proc.terminate()
        self.proc.wait(timeout=5)


HELP = """
Commands:
  init                              Initialize the server
  ping                              Send ping
  tools                             List available tools
  resources                         List available resources
  call <tool> [json_args]           Call a tool (e.g. call execute_command {"command":"id"})
  read <uri>                        Read a resource (e.g. read system://info)
  raw <json>                        Send raw JSON-RPC message
  help                              Show this help
  quit / exit                       Exit
""".strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive MCP REPL")
    parser.add_argument("--docker", metavar="CONTAINER", help="Target Docker container")
    args = parser.parse_args()

    if args.docker:
        cmd = ["docker", "exec", "-i", args.docker, "python3", "/opt/mcp_server.py"]
    else:
        server_path = Path(__file__).resolve().parent.parent / "mcp_server.py"
        cmd = [sys.executable, str(server_path)]

    print(f"Starting: {' '.join(cmd)}")
    repl = MCPRepl(cmd)
    print("Type 'help' for commands, 'quit' to exit.\n")

    try:
        while True:
            try:
                line = input("mcp> ").strip()
            except EOFError:
                break

            if not line:
                continue

            cmd_name = line.split()[0].lower()
            rest = line[len(cmd_name):].strip()

            if cmd_name in ("quit", "exit"):
                break
            elif cmd_name == "help":
                print(HELP)
            elif cmd_name == "init":
                repl.cmd_init()
            elif cmd_name == "ping":
                repl.cmd_ping()
            elif cmd_name == "tools":
                repl.cmd_tools()
            elif cmd_name == "resources":
                repl.cmd_resources()
            elif cmd_name == "call":
                repl.cmd_call(rest)
            elif cmd_name == "read":
                repl.cmd_read(rest)
            elif cmd_name == "raw":
                repl.cmd_raw(rest)
            else:
                print(f"Unknown command: {cmd_name}. Type 'help' for commands.")
    except KeyboardInterrupt:
        print()
    finally:
        repl.close()
        print("Bye.")


if __name__ == "__main__":
    main()
