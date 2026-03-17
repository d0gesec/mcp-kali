"""
Background task management for long-running commands.

Provides a manager for executing commands in the background and retrieving
their output asynchronously.
"""
import logging
import os
import subprocess
import sys
import time
import uuid
from typing import Any

# Logging
logging.basicConfig(
    stream=sys.stderr,
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("pownie-kali-mcp")


class BackgroundTaskManager:
    """Manages background command execution tasks."""

    def __init__(self, output_dir: str = "/workspace/.bg_tasks"):
        """
        Initialize the background task manager.

        Args:
            output_dir: Directory to store task output files
        """
        self.tasks: dict[str, dict[str, Any]] = {}
        self.output_dir = output_dir

        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        log.info("BackgroundTaskManager initialized: output_dir=%s", output_dir)

    def create_task(self, command: str, timeout: int = 3600, name: str | None = None) -> dict[str, str]:
        """
        Create a new background task.

        Args:
            command: Shell command to execute
            timeout: Maximum execution time in seconds
            name: Optional friendly name for the task

        Returns:
            Dictionary with task_id and output_file
        """
        task_id = str(uuid.uuid4())[:12]
        output_file = os.path.join(self.output_dir, f"{task_id}.log")

        log.info("Creating background task: task_id=%s name=%s command=%s",
                 task_id, name or "unnamed", command[:100])

        # Start the process with output redirected to file
        try:
            # Open the output file
            out_fd = open(output_file, 'w')

            process = subprocess.Popen(
                command,
                shell=True,
                stdin=subprocess.DEVNULL,
                stdout=out_fd,
                stderr=subprocess.STDOUT,
                cwd="/workspace"
            )

            # Store task metadata
            self.tasks[task_id] = {
                "task_id": task_id,
                "command": command,
                "process": process,
                "output_file": output_file,
                "output_fd": out_fd,
                "status": "running",
                "start_time": time.time(),
                "timeout": timeout,
                "name": name or f"task-{task_id}",
                "exit_code": None
            }

            log.info("Background task created: task_id=%s pid=%d output=%s",
                     task_id, process.pid, output_file)

            return {
                "task_id": task_id,
                "output_file": output_file,
                "name": self.tasks[task_id]["name"]
            }

        except Exception as e:
            log.error("Failed to create background task: error=%s", str(e))
            return {"error": str(e)}

    def get_task_output(self, task_id: str, tail_lines: int | None = None,
                        wait: bool = True, timeout: int = 30) -> dict[str, Any]:
        """
        Get output from a background task.

        Args:
            task_id: Task identifier
            tail_lines: If specified, return only last N lines
            wait: If True, block until task completes or new output appears
            timeout: Max seconds to wait (capped at 120)

        Returns:
            Dictionary with task status and output
        """
        if task_id not in self.tasks:
            log.warning("Task not found: task_id=%s", task_id)
            return {"error": f"Task not found: {task_id}"}

        task = self.tasks[task_id]
        timeout = min(max(timeout, 1), 120)

        # Update task status
        self._update_task_status(task_id)

        # If task already finished or wait disabled, return immediately
        if not wait or task["status"] != "running":
            return self._read_task_output(task_id, tail_lines)

        # Blocking wait: poll until task completes or new output appears
        output_file = task["output_file"]
        initial_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
        deadline = time.time() + timeout

        log.debug("Waiting for task output: task_id=%s initial_size=%d timeout=%d",
                  task_id, initial_size, timeout)

        while time.time() < deadline:
            time.sleep(2)
            self._update_task_status(task_id)

            # Task finished — return immediately
            if task["status"] != "running":
                log.debug("Task finished during wait: task_id=%s status=%s", task_id, task["status"])
                break

            # New output appeared — return it
            current_size = os.path.getsize(output_file) if os.path.exists(output_file) else 0
            if current_size > initial_size:
                log.debug("New output during wait: task_id=%s bytes=%d",
                          task_id, current_size - initial_size)
                break

        return self._read_task_output(task_id, tail_lines)

    def _read_task_output(self, task_id: str, tail_lines: int | None = None) -> dict[str, Any]:
        """Read and return task output."""
        task = self.tasks[task_id]
        output_file = task["output_file"]

        try:
            with open(output_file, 'r') as f:
                if tail_lines:
                    lines = f.readlines()
                    output = ''.join(lines[-tail_lines:])
                else:
                    output = f.read()

            output_size = len(output)
            log.debug("Task output retrieved: task_id=%s status=%s output_bytes=%d",
                     task_id, task["status"], output_size)

            return {
                "task_id": task_id,
                "name": task["name"],
                "command": task["command"],
                "status": task["status"],
                "exit_code": task["exit_code"],
                "runtime": int(time.time() - task["start_time"]),
                "output": output,
                "output_file": output_file
            }

        except Exception as e:
            log.error("Failed to read task output: task_id=%s error=%s", task_id, str(e))
            return {"error": f"Failed to read output: {str(e)}"}

    def list_tasks(self) -> list[dict[str, Any]]:
        """
        List all background tasks.

        Returns:
            List of task metadata dictionaries
        """
        # Update all task statuses
        for task_id in list(self.tasks.keys()):
            self._update_task_status(task_id)

        tasks = []
        for task_id, task in self.tasks.items():
            tasks.append({
                "task_id": task_id,
                "name": task["name"],
                "command": task["command"][:80] + "..." if len(task["command"]) > 80 else task["command"],
                "status": task["status"],
                "exit_code": task["exit_code"],
                "runtime": int(time.time() - task["start_time"]),
                "output_file": task["output_file"]
            })

        log.debug("Task list retrieved: total=%d", len(tasks))
        return tasks

    def stop_task(self, task_id: str) -> dict[str, Any]:
        """
        Stop a running background task.

        Args:
            task_id: Task identifier

        Returns:
            Dictionary with result status
        """
        if task_id not in self.tasks:
            log.warning("Task not found for stop: task_id=%s", task_id)
            return {"error": f"Task not found: {task_id}"}

        task = self.tasks[task_id]

        # Update status first
        self._update_task_status(task_id)

        if task["status"] != "running":
            log.info("Task already stopped: task_id=%s status=%s", task_id, task["status"])
            return {
                "task_id": task_id,
                "status": task["status"],
                "message": f"Task already {task['status']}"
            }

        # Terminate the process
        try:
            process = task["process"]
            process.terminate()

            # Wait up to 5 seconds for graceful termination
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log.warning("Task did not terminate gracefully, killing: task_id=%s", task_id)
                process.kill()
                process.wait()

            task["status"] = "stopped"
            task["exit_code"] = process.returncode

            # Close output file descriptor
            if task.get("output_fd"):
                task["output_fd"].close()

            log.info("Task stopped: task_id=%s exit_code=%s", task_id, task["exit_code"])

            return {
                "task_id": task_id,
                "status": "stopped",
                "exit_code": task["exit_code"]
            }

        except Exception as e:
            log.error("Failed to stop task: task_id=%s error=%s", task_id, str(e))
            return {"error": f"Failed to stop task: {str(e)}"}

    def _update_task_status(self, task_id: str) -> None:
        """
        Update the status of a task based on process state.

        Args:
            task_id: Task identifier
        """
        if task_id not in self.tasks:
            return

        task = self.tasks[task_id]

        if task["status"] != "running":
            return  # Already finished

        process = task["process"]
        returncode = process.poll()

        if returncode is not None:
            # Process has finished
            task["status"] = "completed"
            task["exit_code"] = returncode

            # Close output file descriptor
            if task.get("output_fd"):
                task["output_fd"].close()

            log.info("Task completed: task_id=%s exit_code=%d runtime=%ds",
                     task_id, returncode, int(time.time() - task["start_time"]))

        # Check for timeout
        elif time.time() - task["start_time"] > task["timeout"]:
            log.warning("Task timeout: task_id=%s timeout=%d", task_id, task["timeout"])
            process.kill()
            process.wait()
            task["status"] = "timeout"
            task["exit_code"] = -1

            # Close output file descriptor
            if task.get("output_fd"):
                task["output_fd"].close()

    def shutdown(self) -> None:
        """Clean up all tasks on shutdown."""
        log.info("BackgroundTaskManager shutting down: active_tasks=%d", len(self.tasks))

        for task_id in list(self.tasks.keys()):
            task = self.tasks[task_id]
            if task["status"] == "running":
                try:
                    task["process"].terminate()
                    task["process"].wait(timeout=2)
                except Exception:
                    try:
                        task["process"].kill()
                    except Exception:
                        pass

            # Close file descriptor
            if task.get("output_fd"):
                try:
                    task["output_fd"].close()
                except Exception:
                    pass

        log.info("BackgroundTaskManager shutdown complete")
