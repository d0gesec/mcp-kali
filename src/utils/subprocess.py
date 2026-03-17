"""
Subprocess execution utilities.
"""
import logging
import os
import subprocess
import sys
import threading
from typing import Any

from ..config.constants import DEFAULT_COMMAND_TIMEOUT, MAX_OUTPUT_BYTES

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")

# Global registry for tracking active synchronous subprocesses
_active_processes: set[subprocess.Popen] = set()
_process_lock = threading.Lock()


def _register_process(proc: subprocess.Popen) -> None:
    """Register an active subprocess for cleanup tracking."""
    with _process_lock:
        _active_processes.add(proc)
        log.debug("Registered subprocess: pid=%d total_active=%d", proc.pid, len(_active_processes))


def _unregister_process(proc: subprocess.Popen) -> None:
    """Unregister a completed subprocess."""
    with _process_lock:
        _active_processes.discard(proc)
        log.debug("Unregistered subprocess: pid=%d total_active=%d", proc.pid, len(_active_processes))


def cleanup_all_processes() -> None:
    """
    Kill all active synchronous subprocesses.

    This is called during server shutdown to ensure no orphaned processes remain.
    """
    with _process_lock:
        if not _active_processes:
            log.debug("No active synchronous subprocesses to clean up")
            return

        log.warning("Cleaning up %d active synchronous subprocess(es)", len(_active_processes))

        for proc in list(_active_processes):
            try:
                if proc.poll() is None:  # Process still running
                    log.info("Terminating synchronous subprocess: pid=%d", proc.pid)
                    proc.terminate()

                    # Give it 2 seconds to terminate gracefully
                    try:
                        proc.wait(timeout=2)
                        log.debug("Subprocess terminated gracefully: pid=%d", proc.pid)
                    except subprocess.TimeoutExpired:
                        log.warning("Subprocess did not terminate gracefully, killing: pid=%d", proc.pid)
                        proc.kill()
                        try:
                            proc.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            log.error("Failed to kill subprocess: pid=%d", proc.pid)
            except Exception as e:
                log.error("Error cleaning up subprocess: pid=%d error=%s", proc.pid, str(e))

        # Clear the registry
        _active_processes.clear()
        log.info("Subprocess cleanup complete")


def execute_subprocess(
    command: str | list[str],
    timeout: int = DEFAULT_COMMAND_TIMEOUT,
    cwd: str | None = None,
) -> dict[str, Any]:
    """
    Run a shell command and capture output safely with streaming support.

    Uses Popen.communicate() which properly handles:
    - Real-time output capture (no buffering delay)
    - Timeout handling
    - Proper process cleanup

    Args:
        command: Shell command string or list of arguments
        timeout: Maximum execution time in seconds
        cwd: Working directory (defaults to /workspace)

    Returns:
        dict with stdout, stderr, exit_code, and timed_out flag
    """
    default_cwd = cwd or "/workspace"
    if not os.path.isdir(default_cwd):
        default_cwd = None  # fall back to current directory
    use_shell = isinstance(command, str)

    log.debug("Subprocess starting: cwd=%s shell=%s", default_cwd, use_shell)

    proc = None
    try:
        # Use Popen for better control and streaming
        proc = subprocess.Popen(
            command,
            shell=use_shell,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=default_cwd,
        )

        # Register the process for cleanup tracking
        _register_process(proc)

        try:
            # communicate() handles streaming and respects timeout
            stdout_bytes, stderr_bytes = proc.communicate(timeout=timeout)

            stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

            log.debug("Subprocess completed: returncode=%d", proc.returncode)

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "timed_out": False,
            }
        finally:
            # Always unregister the process when done
            _unregister_process(proc)

    except subprocess.TimeoutExpired:
        # Process timed out - kill it and get partial output
        if proc:
            proc.kill()
            try:
                stdout_bytes, stderr_bytes = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                # Force kill if still not dead
                proc.kill()
                stdout_bytes, stderr_bytes = b"", b""

            # Unregister the process
            _unregister_process(proc)

            stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
            stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]

            log.warning("Subprocess timed out: timeout=%d", timeout)

            return {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": -1,
                "timed_out": True,
            }
        else:
            log.error("Subprocess timeout but proc is None")
            return {
                "stdout": "",
                "stderr": "Subprocess timeout before process creation",
                "exit_code": -1,
                "timed_out": True,
            }
    except Exception as exc:
        if proc:
            _unregister_process(proc)
        log.error("Subprocess failed: error=%s", str(exc))
        return {
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
            "timed_out": False,
        }
