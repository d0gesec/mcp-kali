"""Tests for concurrent tool execution."""

import concurrent.futures
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from src.utils.subprocess import execute_subprocess


# ---------------------------------------------------------------------------
# execute_subprocess concurrency
# ---------------------------------------------------------------------------


class TestSubprocessConcurrency:
    """Test that multiple subprocess calls can run in parallel."""

    def test_parallel_commands(self):
        """Run 3 commands in parallel and verify all complete."""
        commands = ["echo one", "echo two", "echo three"]
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(execute_subprocess, cmd) for cmd in commands]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        assert len(results) == 3
        outputs = {r["stdout"].strip() for r in results}
        assert outputs == {"one", "two", "three"}

    def test_parallel_with_one_slow(self):
        """One slow command shouldn't block fast ones."""
        start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            fast1 = pool.submit(execute_subprocess, "echo fast1")
            fast2 = pool.submit(execute_subprocess, "echo fast2")
            slow = pool.submit(execute_subprocess, "sleep 2 && echo slow", timeout=5)

            # Fast ones should complete quickly
            r1 = fast1.result(timeout=5)
            r2 = fast2.result(timeout=5)
            assert "fast1" in r1["stdout"]
            assert "fast2" in r2["stdout"]

            r3 = slow.result(timeout=10)
            assert "slow" in r3["stdout"]

    def test_parallel_timeout_isolation(self):
        """A timed-out command should not affect others."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            timeout_cmd = pool.submit(execute_subprocess, "sleep 30", timeout=2)
            fast_cmd = pool.submit(execute_subprocess, "echo ok")

            fast_result = fast_cmd.result(timeout=10)
            assert fast_result["exit_code"] == 0
            assert "ok" in fast_result["stdout"]

            timeout_result = timeout_cmd.result(timeout=10)
            assert timeout_result["timed_out"] is True


# ---------------------------------------------------------------------------
# Concurrent JSON-RPC requests via subprocess
# ---------------------------------------------------------------------------


class TestConcurrentServerRequests:
    """Test sending multiple JSON-RPC requests to the server concurrently
    via a subprocess (simulating multiple Claude Code tool calls)."""

    @pytest.fixture
    def server_proc(self):
        """Start the MCP server as a subprocess."""
        server_path = Path(__file__).resolve().parent.parent / "mcp_server.py"
        proc = subprocess.Popen(
            [sys.executable, str(server_path)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Initialize
        init_msg = json.dumps({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                       "clientInfo": {"name": "test", "version": "0.0"}},
        }) + "\n"
        proc.stdin.write(init_msg)
        proc.stdin.flush()
        proc.stdout.readline()  # consume init response
        yield proc
        try:
            proc.stdin.close()
        except OSError:
            pass
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

    def test_sequential_rapid_fire(self, server_proc):
        """Send many requests in rapid succession."""
        responses = []
        for i in range(1, 11):
            msg = json.dumps({
                "jsonrpc": "2.0",
                "id": i,
                "method": "tools/call",
                "params": {"name": "execute_command", "arguments": {"command": f"echo msg{i}"}},
            }) + "\n"
            server_proc.stdin.write(msg)
            server_proc.stdin.flush()

        # Read all responses
        for _ in range(10):
            line = server_proc.stdout.readline()
            assert line, "Expected a response line"
            resp = json.loads(line)
            responses.append(resp)

        # All should be successful
        assert len(responses) == 10
        ids = {r["id"] for r in responses}
        assert ids == set(range(1, 11))
        for r in responses:
            assert "result" in r
            assert r["result"]["isError"] is False

    def test_interleaved_methods(self, server_proc):
        """Mix different method types in rapid succession."""
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
             "params": {"name": "execute_command", "arguments": {"command": "echo hi"}}},
            {"jsonrpc": "2.0", "id": 5, "method": "resources/read",
             "params": {"uri": "system://info"}},
        ]
        for msg in messages:
            server_proc.stdin.write(json.dumps(msg) + "\n")
            server_proc.stdin.flush()

        responses = {}
        for _ in range(5):
            line = server_proc.stdout.readline()
            resp = json.loads(line)
            responses[resp["id"]] = resp

        # All should succeed
        assert len(responses) == 5
        assert "result" in responses[1]  # ping
        assert "tools" in responses[2]["result"]  # tools/list
        assert "resources" in responses[3]["result"]  # resources/list
        assert responses[4]["result"]["isError"] is False  # tools/call
        assert "contents" in responses[5]["result"]  # resources/read
