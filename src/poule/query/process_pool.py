"""Standalone Coq process pool for session-free query execution."""

from __future__ import annotations


class ProcessPool:
    """Pool of standalone Coq processes for session-free vernacular queries.

    Each invocation uses one process; no shared state between invocations.
    The process is acquired before command execution and released after output
    is received.
    """

    async def send_command(self, command: str) -> str:
        """Send a vernacular command string to a standalone Coq process.

        Args:
            command: The full Coq vernacular string (e.g. "Check nat.").

        Returns:
            The raw Coq output string.

        Raises:
            RuntimeError: If the Coq backend process crashes.
        """
        raise NotImplementedError(
            "ProcessPool.send_command requires a real Coq backend."
        )
