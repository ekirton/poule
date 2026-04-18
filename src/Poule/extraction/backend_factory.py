"""Backend factory for Coq extraction.

Poule targets a single extraction backend (coq-lsp) per the
single-backend decision in ``doc/features/library-indexing.md``.
"""

from __future__ import annotations

import shutil

from .coq_backend import CoqBackend
from .errors import CoqNotInstalledError


def create_coq_backend() -> CoqBackend:
    """Create and return a coq-lsp backend instance.

    Raises
    ------
    CoqNotInstalledError
        If ``coq-lsp`` is not found on the system.
    """
    if shutil.which("coq-lsp") is None:
        raise CoqNotInstalledError()

    from Poule.extraction.backends.coqlsp_backend import CoqLspBackend  # type: ignore[import-not-found]
    return CoqLspBackend()
