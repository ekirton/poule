"""Tests for diagram_dir CLI/env wiring in the MCP server entry point.

Verifies that:
- The --diagram-dir CLI argument is parsed and propagated to server context
- The POULE_MCP_DIAGRAM_DIR env var serves as a fallback
- When neither is set, diagram_dir remains None

Spec: specification/diagram-file-output.md §5 (handler integration)
Architecture: doc/architecture/diagram-file-output.md (container configuration)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Tests: CLI --diagram-dir flag
# ---------------------------------------------------------------------------

class TestDiagramDirCliFlag:
    """--diagram-dir CLI argument parsing."""

    def test_flag_sets_diagram_dir(self):
        """--diagram-dir /tmp/proj passes Path('/tmp/proj') to run_server."""
        def fake_run(coro):
            coro.close()

        with (
            patch("sys.argv", ["poule-server", "--diagram-dir", "/tmp/proj"]),
            patch("Poule.server.__main__.asyncio") as mock_asyncio,
            patch("Poule.server.__main__.run_server") as mock_run,
        ):
            mock_asyncio.run = fake_run
            mock_run.return_value = None

            from Poule.server.__main__ import main
            main()

            _, kwargs = mock_run.call_args
            assert kwargs["diagram_dir"] == Path("/tmp/proj")

    def test_flag_not_set_defaults_to_none(self):
        """Without --diagram-dir or env var, diagram_dir is None."""
        captured = {}

        def fake_run(coro):
            coro.close()

        env_clean = {k: v for k, v in __import__("os").environ.items() if k != "POULE_MCP_DIAGRAM_DIR"}

        with (
            patch("sys.argv", ["poule-server"]),
            patch("Poule.server.__main__.asyncio") as mock_asyncio,
            patch("Poule.server.__main__.run_server") as mock_run,
            patch.dict("os.environ", env_clean, clear=True),
        ):
            mock_asyncio.run = fake_run
            mock_run.return_value = None

            from Poule.server.__main__ import main
            main()

            _, kwargs = mock_run.call_args
            assert kwargs["diagram_dir"] is None

    def test_flag_passed_to_http_transport(self):
        """--diagram-dir is forwarded to run_server_http for streamable-http transport."""

        def fake_run(coro):
            coro.close()

        with (
            patch("sys.argv", ["poule-server", "--transport", "streamable-http", "--diagram-dir", "/proj"]),
            patch("Poule.server.__main__.asyncio") as mock_asyncio,
            patch("Poule.server.__main__.run_server_http") as mock_run_http,
        ):
            mock_asyncio.run = fake_run
            mock_run_http.return_value = None

            from Poule.server.__main__ import main
            main()

            _, kwargs = mock_run_http.call_args
            assert kwargs["diagram_dir"] == Path("/proj")


# ---------------------------------------------------------------------------
# Tests: POULE_MCP_DIAGRAM_DIR env var fallback
# ---------------------------------------------------------------------------

class TestDiagramDirEnvFallback:
    """POULE_MCP_DIAGRAM_DIR environment variable used when --diagram-dir is absent."""

    def test_env_var_used_when_flag_absent(self):
        """POULE_MCP_DIAGRAM_DIR=/data/project → diagram_dir=Path('/data/project')."""

        def fake_run(coro):
            coro.close()

        with (
            patch("sys.argv", ["poule-server"]),
            patch("Poule.server.__main__.asyncio") as mock_asyncio,
            patch("Poule.server.__main__.run_server") as mock_run,
            patch.dict("os.environ", {"POULE_MCP_DIAGRAM_DIR": "/data/project"}),
        ):
            mock_asyncio.run = fake_run
            mock_run.return_value = None

            from Poule.server.__main__ import main
            main()

            _, kwargs = mock_run.call_args
            assert kwargs["diagram_dir"] == Path("/data/project")

    def test_flag_overrides_env_var(self):
        """--diagram-dir takes precedence over POULE_MCP_DIAGRAM_DIR."""

        def fake_run(coro):
            coro.close()

        with (
            patch("sys.argv", ["poule-server", "--diagram-dir", "/from-flag"]),
            patch("Poule.server.__main__.asyncio") as mock_asyncio,
            patch("Poule.server.__main__.run_server") as mock_run,
            patch.dict("os.environ", {"POULE_MCP_DIAGRAM_DIR": "/from-env"}),
        ):
            mock_asyncio.run = fake_run
            mock_run.return_value = None

            from Poule.server.__main__ import main
            main()

            _, kwargs = mock_run.call_args
            assert kwargs["diagram_dir"] == Path("/from-flag")

    def test_empty_env_var_treated_as_absent(self):
        """POULE_MCP_DIAGRAM_DIR='' → diagram_dir remains None."""

        def fake_run(coro):
            coro.close()

        with (
            patch("sys.argv", ["poule-server"]),
            patch("Poule.server.__main__.asyncio") as mock_asyncio,
            patch("Poule.server.__main__.run_server") as mock_run,
            patch.dict("os.environ", {"POULE_MCP_DIAGRAM_DIR": ""}, clear=False),
        ):
            mock_asyncio.run = fake_run
            mock_run.return_value = None

            from Poule.server.__main__ import main
            main()

            _, kwargs = mock_run.call_args
            assert kwargs["diagram_dir"] is None


# ---------------------------------------------------------------------------
# Tests: _ServerContext default
# ---------------------------------------------------------------------------

class TestServerContextDefault:
    """_ServerContext initializes diagram_dir to None."""

    def test_diagram_dir_default_is_none(self):
        from Poule.server.__main__ import _ServerContext
        ctx = _ServerContext()
        assert ctx.diagram_dir is None

    def test_diagram_dir_is_settable(self):
        from Poule.server.__main__ import _ServerContext
        ctx = _ServerContext()
        ctx.diagram_dir = Path("/tmp/test")
        assert ctx.diagram_dir == Path("/tmp/test")
