"""Abstract backend interface for communicating with a Coq subprocess."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CoqBackend(Protocol):
    """Protocol defining the operations a Coq backend must support.

    Backends communicate with an external tool (coq-lsp or SerAPI) to read
    compiled ``.vo`` files and access kernel terms.
    """

    def list_declarations(
        self, vo_path: Path, *, rss_check: Callable[[], None] | None = None,
    ) -> list[tuple[str, str, Any]]:
        """List all declarations in a compiled ``.vo`` file.

        Parameters
        ----------
        vo_path:
            Path to a compiled ``.vo`` file.
        rss_check:
            Optional callback invoked between internal batches to allow
            the caller to restart the backend when RSS is too high.

        Returns
        -------
        list[tuple[str, str, Any]]
            A list of ``(name, kind, constr_t)`` tuples.
        """
        ...

    def pretty_print(self, name: str) -> str:
        """Return the human-readable statement string for a declaration.

        Parameters
        ----------
        name:
            Fully qualified declaration name.
        """
        ...

    def pretty_print_type(self, name: str) -> str | None:
        """Return the human-readable type signature, or None.

        Parameters
        ----------
        name:
            Fully qualified declaration name.
        """
        ...

    def get_dependencies(self, name: str) -> list[tuple[str, str]]:
        """Return dependency pairs for a declaration.

        Parameters
        ----------
        name:
            Fully qualified declaration name.

        Returns
        -------
        list[tuple[str, str]]
            A list of ``(target_name, relation)`` pairs.
        """
        ...

    def detect_version(self) -> str:
        """Detect and return the Coq/Rocq version string (e.g. ``"8.19"``)."""
        ...
