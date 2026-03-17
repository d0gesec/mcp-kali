"""
Session management for persistent interactive PTY sessions.

Provides SessionManager class for managing long-lived terminal sessions
(telnet, SSH, netcat, interactive shells, etc.) with background output
buffering and thread-safe I/O operations.
"""
import errno
import fcntl
import logging
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import threading
import time
import tty
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from ..config.constants import (
    MAX_SESSIONS,
    PTY_READ_CHUNK_SIZE,
    SESSION_BUFFER_SIZE,
    SESSION_CLEANUP_INTERVAL,
    SESSION_DEFAULT_READ_TIMEOUT,
    SESSION_IDLE_TIMEOUT,
    SESSION_READ_POLL_INTERVAL,
)

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")

# ANSI escape code pattern for stripping terminal control sequences
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[=>]')


def strip_ansi_codes(text: str) -> str:
    """
    Remove ANSI escape codes from text.

    Strips:
    - CSI sequences (colors, cursor movement, etc.)
    - OSC sequences (set window title, etc.)
    - Other terminal control codes

    Args:
        text: Raw terminal output with ANSI codes

    Returns:
        Clean text with ANSI codes removed
    """
    return ANSI_ESCAPE_PATTERN.sub('', text)


def configure_pty_for_raw_mode(fd: int) -> None:
    """
    Configure PTY terminal settings for reliable non-interactive use.

    Disables:
    - Echo (prevents command echo duplication)
    - Canonical mode (process input immediately, not line-by-line)
    - Signal generation (^C, ^Z won't kill the session)

    Args:
        fd: PTY master file descriptor
    """
    try:
        # Get current terminal attributes
        attrs = termios.tcgetattr(fd)

        # Disable echo - prevents commands from being echoed back
        attrs[3] = attrs[3] & ~termios.ECHO

        # Apply settings
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        log.debug("PTY configured: echo disabled for fd=%d", fd)
    except (termios.error, OSError) as e:
        # Non-fatal - some PTYs may not support all settings
        log.warning("PTY configuration failed: fd=%d error=%s", fd, str(e))


@dataclass
class SessionContext:
    """Encapsulates all state for a single PTY session."""

    # Identity
    session_id: str
    name: Optional[str]
    command: str

    # Process & PTY
    process: subprocess.Popen
    master_fd: int

    # Threading
    reader_thread: threading.Thread
    session_lock: threading.Lock = field(default_factory=threading.Lock)
    stop_event: threading.Event = field(default_factory=threading.Event)

    # Output buffering (ring buffer with automatic FIFO dropping)
    output_buffer: deque = field(default_factory=lambda: deque(maxlen=25))  # 25 * 4KB = 100KB

    # Metadata
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    last_output_time: float = field(default_factory=time.time)  # Track when output was last received
    status: str = "running"  # "running", "stopped", "error"
    exit_code: Optional[int] = None

    # Statistics
    bytes_read: int = 0
    bytes_written: int = 0
    read_count: int = 0
    write_count: int = 0


class SessionManager:
    """Manages persistent interactive PTY sessions for security tools."""

    def __init__(
        self,
        max_sessions: int = MAX_SESSIONS,
        buffer_size: int = SESSION_BUFFER_SIZE,
        idle_timeout: int = SESSION_IDLE_TIMEOUT,
    ) -> None:
        """
        Initialize the session manager.

        Args:
            max_sessions: Maximum number of concurrent sessions
            buffer_size: Maximum buffered output per session (bytes)
            idle_timeout: Seconds before idle session is terminated
        """
        self._sessions: dict[str, SessionContext] = {}
        self._global_lock = threading.Lock()
        self._max_sessions = max_sessions
        self._buffer_size = buffer_size
        self._idle_timeout = idle_timeout
        self._cleanup_thread: Optional[threading.Thread] = None
        self._shutdown_event = threading.Event()

        log.info("SessionManager initialized: max_sessions=%d buffer_size=%d idle_timeout=%d",
                 max_sessions, buffer_size, idle_timeout)

        # Start background cleanup thread
        self._start_cleanup_thread()

    def _start_cleanup_thread(self) -> None:
        """Start the background cleanup thread for idle sessions."""
        self._cleanup_thread = threading.Thread(
            target=self._cleanup_idle_sessions,
            name="SessionCleanup",
            daemon=True,
        )
        self._cleanup_thread.start()
        log.debug("Session cleanup thread started")

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return uuid.uuid4().hex[:12]

    def _is_process_alive(self, ctx: SessionContext) -> bool:
        """
        Check if the session's child process is still running.

        Args:
            ctx: Session context to check

        Returns:
            True if process is alive, False if dead/zombie
        """
        try:
            # WNOHANG returns immediately; returns (0, 0) if process is still running
            pid, status = os.waitpid(ctx.process.pid, os.WNOHANG)
            if pid == 0:
                return True  # Process still running
            else:
                # Process has exited - update context
                if os.WIFEXITED(status):
                    ctx.exit_code = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    ctx.exit_code = -os.WTERMSIG(status)
                ctx.status = "stopped"
                return False
        except ChildProcessError:
            # No child process - already reaped
            ctx.status = "stopped"
            return False
        except Exception as e:
            log.warning("Process alive check failed: session_id=%s error=%s", ctx.session_id, str(e))
            return True  # Assume alive if we can't check

    def create_session(self, command: str, name: Optional[str] = None, timeout: int = 300) -> dict[str, Any]:
        """
        Create a new persistent PTY session.

        Args:
            command: Shell command to execute
            name: Optional friendly name for the session
            timeout: Initial timeout (unused currently, for future use)

        Returns:
            dict with success status, session_id, and metadata
        """
        if self._shutdown_event.is_set():
            log.warning("Session creation rejected: server is shutting down")
            return {"success": False, "error": "Server is shutting down"}

        with self._global_lock:
            if len(self._sessions) >= self._max_sessions:
                log.warning("Session creation failed: reason=limit_reached current=%d max=%d",
                           len(self._sessions), self._max_sessions)
                return {
                    "success": False,
                    "error": f"Session limit reached ({len(self._sessions)}/{self._max_sessions})",
                    "active_sessions": len(self._sessions),
                }

            session_id = self._generate_session_id()

            try:
                # Fork PTY
                pid, master_fd = pty.fork()

                if pid == 0:
                    # Child process: exec the command
                    try:
                        os.execvp("/bin/sh", ["/bin/sh", "-c", command])
                    except Exception as e:
                        log.error("Child process exec failed: error=%s", str(e))
                        os._exit(1)

                # Parent process: setup session
                # Set master fd to non-blocking
                flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
                fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

                # Configure PTY for reliable output (disable echo, etc.)
                configure_pty_for_raw_mode(master_fd)

                # Create process object for tracking
                # Note: Popen not used here since we forked manually with pty.fork()
                # We'll track the PID directly
                process = type('Process', (), {'pid': pid, 'poll': lambda: None})()

                # Create session context
                ctx = SessionContext(
                    session_id=session_id,
                    name=name,
                    command=command,
                    process=process,
                    master_fd=master_fd,
                    reader_thread=None,  # Will be set below
                )

                # Start reader thread
                reader_thread = threading.Thread(
                    target=self._reader_thread_func,
                    args=(ctx,),
                    name=f"SessionReader-{session_id}",
                    daemon=True,
                )
                ctx.reader_thread = reader_thread
                reader_thread.start()

                # Register session
                self._sessions[session_id] = ctx

                log.info("Session created: session_id=%s name=%s command=%s pid=%d",
                        session_id, name or "unnamed", command[:50], pid)

                # Minimal response - only session_id needed for follow-up calls
                return {
                    "session_id": session_id,
                }

            except OSError as e:
                log.error("Session creation failed: error=%s errno=%d", str(e), e.errno)
                return {
                    "success": False,
                    "error": f"PTY fork failed: {str(e)}",
                }
            except Exception as e:
                log.exception("Session creation failed: error=%s", str(e))
                return {
                    "success": False,
                    "error": f"Unexpected error: {str(e)}",
                }

    def _reader_thread_func(self, ctx: SessionContext) -> None:
        """
        Background thread that continuously reads from PTY and buffers output.

        Args:
            ctx: Session context to read from
        """
        log.debug("Reader thread started: session_id=%s", ctx.session_id)

        while not ctx.stop_event.is_set() and not self._shutdown_event.is_set():
            try:
                # Use select with timeout for non-blocking read
                readable, _, exceptional = select.select(
                    [ctx.master_fd], [], [ctx.master_fd], SESSION_READ_POLL_INTERVAL
                )

                if ctx.master_fd in readable:
                    try:
                        data = os.read(ctx.master_fd, PTY_READ_CHUNK_SIZE)
                        if not data:
                            # EOF - process terminated
                            log.debug("Reader thread: session_id=%s reason=eof", ctx.session_id)
                            ctx.status = "stopped"
                            break

                        with ctx.session_lock:
                            ctx.output_buffer.append(data)
                            ctx.bytes_read += len(data)
                            ctx.last_activity = time.time()
                            ctx.last_output_time = time.time()  # Track output timing

                    except OSError as e:
                        if e.errno == errno.EIO:
                            # Process died
                            log.debug("Reader thread: session_id=%s reason=process_died", ctx.session_id)
                            ctx.status = "stopped"
                            break
                        elif e.errno == errno.EAGAIN:
                            # No data available (shouldn't happen with select, but handle it)
                            continue
                        else:
                            log.error("Reader thread error: session_id=%s error=%s", ctx.session_id, str(e))
                            raise

                if ctx.master_fd in exceptional:
                    log.warning("Reader thread: session_id=%s reason=exceptional_condition", ctx.session_id)
                    ctx.status = "error"
                    break

            except Exception as e:
                log.exception("Reader thread exception: session_id=%s error=%s", ctx.session_id, str(e))
                ctx.status = "error"
                break

        log.debug("Reader thread stopped: session_id=%s status=%s", ctx.session_id, ctx.status)

        # Cleanup session resources when thread exits
        self._cleanup_session_resources(ctx)

    def _cleanup_session_resources(self, ctx: SessionContext) -> None:
        """
        Cleanup PTY file descriptor and process for a session.

        Args:
            ctx: Session context to cleanup
        """
        log.debug("Cleaning up session resources: session_id=%s", ctx.session_id)

        # Close PTY master
        try:
            os.close(ctx.master_fd)
            log.debug("PTY closed: session_id=%s fd=%d", ctx.session_id, ctx.master_fd)
        except OSError as e:
            if e.errno != errno.EBADF:
                log.warning("PTY close failed: session_id=%s error=%s", ctx.session_id, str(e))

        # Check if process exited and get exit code
        try:
            pid, status = os.waitpid(ctx.process.pid, os.WNOHANG)
            if pid != 0:
                if os.WIFEXITED(status):
                    ctx.exit_code = os.WEXITSTATUS(status)
                    log.debug("Process exited: session_id=%s pid=%d exit_code=%d",
                             ctx.session_id, ctx.process.pid, ctx.exit_code)
                elif os.WIFSIGNALED(status):
                    ctx.exit_code = -os.WTERMSIG(status)
                    log.debug("Process signaled: session_id=%s pid=%d signal=%d",
                             ctx.session_id, ctx.process.pid, -ctx.exit_code)
        except ChildProcessError:
            # Process already reaped
            pass
        except Exception as e:
            log.warning("waitpid failed: session_id=%s error=%s", ctx.session_id, str(e))

    def send_to_session(
        self, session_id: str, input_data: str = "", read_timeout: int = SESSION_DEFAULT_READ_TIMEOUT
    ) -> dict[str, Any]:
        """
        Send input to a session and read buffered output.

        Args:
            session_id: Session ID from create_session
            input_data: Input to send (empty string to just read output)
            read_timeout: How long to wait for output (seconds)

        Returns:
            dict with success status, output, and metadata
        """
        with self._global_lock:
            ctx = self._sessions.get(session_id)
            if not ctx:
                log.warning("Session send failed: session_id=%s reason=not_found", session_id)
                return {
                    "success": False,
                    "error": f"Session not found: {session_id}",
                    "available_sessions": list(self._sessions.keys()),
                }

        # Write input if provided
        if input_data:
            # Ensure command ends with newline to prevent concatenation
            if not input_data.endswith('\n'):
                input_data = input_data + '\n'

            # Log the command being sent (truncate if too long, escape newlines for readability)
            display_input = input_data.replace('\n', '\\n').replace('\r', '\\r')
            if len(display_input) > 200:
                display_input = display_input[:200] + "..."
            log.info("Session command: session_id=%s name=%s input='%s'",
                    session_id, ctx.name or "unnamed", display_input)

            try:
                self._write_to_pty(ctx, input_data)
            except Exception as e:
                log.error("Write to PTY failed: session_id=%s error=%s", session_id, str(e))
                return {
                    "success": False,
                    "error": f"Write failed: {str(e)}",
                    "status": ctx.status,
                }

        # Read buffered output
        try:
            output_bytes = self._read_buffered_output(ctx, read_timeout)
            output_raw = output_bytes.decode("utf-8", errors="replace")

            # Strip ANSI escape codes for clean LLM-friendly output
            output = strip_ansi_codes(output_raw)

            log.debug("Session send completed: session_id=%s bytes_written=%d bytes_read=%d stripped=%d",
                     session_id, len(input_data), len(output_bytes), len(output_raw) - len(output))

            # Check process status for diagnostic info
            process_alive = self._is_process_alive(ctx)
            current_time = time.time()
            since_last_output = round(current_time - ctx.last_output_time, 1)

            # Enhanced response with diagnostic info for debugging
            return {
                "output": output,
                "status": ctx.status,
                "alive": process_alive,
                "since_output": since_last_output,  # Seconds since last output received
                "exit_code": ctx.exit_code,
            }

        except Exception as e:
            log.exception("Read from session failed: session_id=%s error=%s", session_id, str(e))
            return {
                "success": False,
                "error": f"Read failed: {str(e)}",
                "status": ctx.status,
            }

    def _write_to_pty(self, ctx: SessionContext, data: str) -> None:
        """
        Write input to PTY master with locking.

        Args:
            ctx: Session context
            data: String to write

        Raises:
            OSError: If write fails (e.g., EIO when PTY closed)
        """
        with ctx.session_lock:
            try:
                encoded = data.encode("utf-8")
                written = os.write(ctx.master_fd, encoded)
                ctx.bytes_written += written
                ctx.write_count += 1
                ctx.last_activity = time.time()
                log.debug("Wrote to PTY: session_id=%s bytes=%d", ctx.session_id, written)
            except OSError as e:
                if e.errno == errno.EIO:
                    ctx.status = "stopped"
                    raise OSError(f"Session {ctx.session_id} has terminated") from e
                raise

    def _read_buffered_output(self, ctx: SessionContext, timeout: float) -> bytes:
        """
        Read all available buffered output during the timeout period.

        Continuously collects output until the timeout expires, ensuring
        all output from long-running commands (with sleeps/delays) is captured.

        Args:
            ctx: Session context
            timeout: Seconds to wait and collect output

        Returns:
            Accumulated bytes from buffer
        """
        accumulated_chunks = []

        if timeout > 0:
            deadline = time.time() + timeout

            while time.time() < deadline:
                with ctx.session_lock:
                    if ctx.output_buffer:
                        # Collect any available data
                        chunks = list(ctx.output_buffer)
                        ctx.output_buffer.clear()
                        accumulated_chunks.extend(chunks)

                time.sleep(SESSION_READ_POLL_INTERVAL)

        # Final collection of any remaining data
        with ctx.session_lock:
            if ctx.output_buffer:
                chunks = list(ctx.output_buffer)
                ctx.output_buffer.clear()
                accumulated_chunks.extend(chunks)

            ctx.read_count += 1
            ctx.last_activity = time.time()

        return b"".join(accumulated_chunks)

    def list_sessions(self) -> list[dict[str, Any]]:
        """
        List all active sessions with metadata.

        Returns:
            List of session metadata dicts
        """
        with self._global_lock:
            sessions = []
            current_time = time.time()

            for ctx in self._sessions.values():
                uptime = current_time - ctx.created_at
                sessions.append({
                    "session_id": ctx.session_id,
                    "name": ctx.name,
                    "command": ctx.command,
                    "status": ctx.status,
                    "created_at": ctx.created_at,
                    "last_activity": ctx.last_activity,
                    "uptime_seconds": round(uptime, 3),
                    "bytes_read": ctx.bytes_read,
                    "bytes_written": ctx.bytes_written,
                    "read_count": ctx.read_count,
                    "write_count": ctx.write_count,
                })

            log.debug("Session list: active_sessions=%d", len(sessions))
            return sessions

    def close_session(self, session_id: str) -> dict[str, Any]:
        """
        Terminate a session and clean up resources.

        Args:
            session_id: Session ID to close

        Returns:
            dict with success status and session info
        """
        with self._global_lock:
            ctx = self._sessions.get(session_id)
            if not ctx:
                log.warning("Session close failed: session_id=%s reason=not_found", session_id)
                return {
                    "success": False,
                    "error": f"Session not found: {session_id}",
                }

            log.info("Closing session: session_id=%s", session_id)

            # Signal reader thread to stop
            ctx.stop_event.set()

            # Remove from registry immediately
            del self._sessions[session_id]

        # Terminate process gracefully (outside lock to avoid deadlock)
        uptime = time.time() - ctx.created_at
        try:
            # Send SIGTERM
            os.kill(ctx.process.pid, signal.SIGTERM)
            log.debug("Sent SIGTERM: session_id=%s pid=%d", session_id, ctx.process.pid)

            # Wait up to 2 seconds
            deadline = time.time() + 2.0
            while time.time() < deadline:
                pid, status = os.waitpid(ctx.process.pid, os.WNOHANG)
                if pid != 0:
                    if os.WIFEXITED(status):
                        ctx.exit_code = os.WEXITSTATUS(status)
                    break
                time.sleep(0.1)
            else:
                # Process didn't die, escalate to SIGKILL
                log.warning("Process didn't respond to SIGTERM, sending SIGKILL: session_id=%s pid=%d",
                           session_id, ctx.process.pid)
                os.kill(ctx.process.pid, signal.SIGKILL)
                os.waitpid(ctx.process.pid, 0)

        except ProcessLookupError:
            # Process already dead
            log.debug("Process already terminated: session_id=%s", session_id)
        except Exception as e:
            log.warning("Process termination error: session_id=%s error=%s", session_id, str(e))

        # Wait for reader thread to finish (with timeout)
        if ctx.reader_thread and ctx.reader_thread.is_alive():
            ctx.reader_thread.join(timeout=5.0)
            if ctx.reader_thread.is_alive():
                log.warning("Reader thread didn't join: session_id=%s", session_id)

        log.info("Session closed: session_id=%s uptime=%.1fs exit_code=%s",
                session_id, uptime, ctx.exit_code)

        # Minimal response - just confirmation
        return {
            "message": "closed",
        }

    def _cleanup_idle_sessions(self) -> None:
        """Background thread that periodically checks for and closes idle sessions."""
        log.debug("Idle cleanup thread started")

        while not self._shutdown_event.is_set():
            time.sleep(SESSION_CLEANUP_INTERVAL)

            current_time = time.time()
            to_close = []

            with self._global_lock:
                for session_id, ctx in self._sessions.items():
                    idle_time = current_time - ctx.last_activity
                    if idle_time > self._idle_timeout:
                        to_close.append(session_id)
                        log.info("Session idle timeout: session_id=%s idle_seconds=%.1f",
                                session_id, idle_time)

            # Close idle sessions (outside lock to avoid deadlock)
            for session_id in to_close:
                self.close_session(session_id)

        log.debug("Idle cleanup thread stopped")

    def shutdown(self) -> None:
        """Shutdown the session manager and close all sessions."""
        log.info("SessionManager shutdown initiated: active_sessions=%d", len(self._sessions))

        # Signal shutdown
        self._shutdown_event.set()

        # Get list of session IDs (copy to avoid modification during iteration)
        with self._global_lock:
            session_ids = list(self._sessions.keys())

        # Close all sessions
        for session_id in session_ids:
            try:
                self.close_session(session_id)
            except Exception as e:
                log.error("Error closing session during shutdown: session_id=%s error=%s",
                         session_id, str(e))

        # Wait for cleanup thread
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5.0)
            if self._cleanup_thread.is_alive():
                log.warning("Cleanup thread didn't stop during shutdown")

        log.info("SessionManager shutdown complete")
