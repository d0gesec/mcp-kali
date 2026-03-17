"""
Rate limiting utilities for package installations.
"""
import time

from ..config.constants import MAX_INSTALLS_PER_HOUR


class InstallRateLimiter:
    """Simple in-memory rate limiter for package installations."""

    def __init__(self, max_per_hour: int = MAX_INSTALLS_PER_HOUR) -> None:
        self.max_per_hour = max_per_hour
        self._timestamps: list[float] = []

    def check(self) -> bool:
        """Return True if installation is allowed."""
        now = time.time()
        cutoff = now - 3600
        self._timestamps = [t for t in self._timestamps if t > cutoff]
        return len(self._timestamps) < self.max_per_hour

    def record(self) -> None:
        self._timestamps.append(time.time())


# Module-level rate limiter (shared across handler calls)
install_limiter = InstallRateLimiter()
