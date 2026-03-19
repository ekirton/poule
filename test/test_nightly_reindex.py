"""Tests for nightly re-index automation.

Spec: specification/nightly-reindex.md §4.1-§4.9, §5
      specification/prebuilt-distribution.md §5 (--replace flag)

Scripts under test:
  scripts/nightly-reindex.sh
  scripts/reindex-cron.sh
  scripts/publish-release.sh (--replace flag addition)
"""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

PROJECT_ROOT = Path("/poule")
NIGHTLY_SCRIPT = PROJECT_ROOT / "scripts" / "nightly-reindex.sh"
CRON_SCRIPT = PROJECT_ROOT / "scripts" / "reindex-cron.sh"
PUBLISH_SCRIPT = PROJECT_ROOT / "scripts" / "publish-release.sh"

nightly_script_exists = pytest.mark.skipif(
    not NIGHTLY_SCRIPT.exists(),
    reason="scripts/nightly-reindex.sh not yet created",
)
cron_script_exists = pytest.mark.skipif(
    not CRON_SCRIPT.exists(),
    reason="scripts/reindex-cron.sh not yet created",
)
publish_script_exists = pytest.mark.skipif(
    not PUBLISH_SCRIPT.exists(),
    reason="scripts/publish-release.sh not yet created",
)


# ═══════════════════════════════════════════════════════════════════════════
# Inner script — scripts/nightly-reindex.sh
# ═══════════════════════════════════════════════════════════════════════════


@nightly_script_exists
class TestNightlyReindexScript:
    """Static properties of scripts/nightly-reindex.sh."""

    def test_script_exists_and_is_executable(self):
        """§8: The inner script must exist and be executable."""
        assert NIGHTLY_SCRIPT.exists(), "scripts/nightly-reindex.sh does not exist"
        mode = NIGHTLY_SCRIPT.stat().st_mode
        assert mode & stat.S_IXUSR, "scripts/nightly-reindex.sh is not executable"

    def test_script_has_bash_shebang(self):
        """§8: The inner script uses #!/usr/bin/env bash."""
        first_line = NIGHTLY_SCRIPT.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", (
            f"Expected bash shebang, got: {first_line}"
        )

    def test_script_uses_strict_mode(self):
        """§8: The inner script uses set -euo pipefail."""
        content = NIGHTLY_SCRIPT.read_text()
        assert "set -euo pipefail" in content, (
            "scripts/nightly-reindex.sh must use set -euo pipefail"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Outer script — scripts/reindex-cron.sh
# ═══════════════════════════════════════════════════════════════════════════


@cron_script_exists
class TestReindexCronScript:
    """Static properties of scripts/reindex-cron.sh."""

    def test_script_exists_and_is_executable(self):
        """§4.9: The outer script must exist and be executable."""
        assert CRON_SCRIPT.exists(), "scripts/reindex-cron.sh does not exist"
        mode = CRON_SCRIPT.stat().st_mode
        assert mode & stat.S_IXUSR, "scripts/reindex-cron.sh is not executable"

    def test_script_has_bash_shebang(self):
        """§8: The outer script uses #!/usr/bin/env bash."""
        first_line = CRON_SCRIPT.read_text().splitlines()[0]
        assert first_line == "#!/usr/bin/env bash", (
            f"Expected bash shebang, got: {first_line}"
        )

    def test_script_uses_strict_mode(self):
        """§8: The outer script uses set -euo pipefail."""
        content = CRON_SCRIPT.read_text()
        assert "set -euo pipefail" in content, (
            "scripts/reindex-cron.sh must use set -euo pipefail"
        )

    def test_script_checks_gh_token(self):
        """§4.9/§5: The outer script validates GH_TOKEN before docker run."""
        content = CRON_SCRIPT.read_text()
        assert "GH_TOKEN" in content, (
            "scripts/reindex-cron.sh must reference GH_TOKEN"
        )
        # The check must appear before the docker run command.
        # Find positions of the GH_TOKEN check and docker run.
        gh_token_pos = content.find("GH_TOKEN")
        docker_run_pos = content.find("docker run")
        assert docker_run_pos > 0, (
            "scripts/reindex-cron.sh must contain a docker run command"
        )
        assert gh_token_pos < docker_run_pos, (
            "GH_TOKEN validation must appear before docker run"
        )

    def test_script_checks_docker(self):
        """§5: The outer script checks for docker command availability."""
        content = CRON_SCRIPT.read_text()
        # The script should check docker is available (command -v docker or which docker)
        assert "docker" in content, (
            "scripts/reindex-cron.sh must reference docker"
        )
        # Expect a command-existence check pattern
        has_check = (
            "command -v docker" in content
            or "which docker" in content
            or "type docker" in content
        )
        assert has_check, (
            "scripts/reindex-cron.sh must check docker is on PATH "
            "(expected 'command -v docker', 'which docker', or 'type docker')"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Publish script — --replace flag
# ═══════════════════════════════════════════════════════════════════════════


@publish_script_exists
class TestPublishReplaceFlag:
    """Tests for the --replace flag addition to scripts/publish-release.sh."""

    def test_publish_script_accepts_replace_flag(self):
        """§4.7: publish-release.sh must handle a --replace flag."""
        content = PUBLISH_SCRIPT.read_text()
        assert "--replace" in content, (
            "scripts/publish-release.sh must accept a --replace flag "
            "(specification/nightly-reindex.md §4.7)"
        )

    def test_publish_script_help_mentions_replace(self):
        """§4.7: --replace appears in usage/help text."""
        content = PUBLISH_SCRIPT.read_text()
        # Find the usage function or help text block
        # The flag should be documented somewhere in the script
        lines = content.splitlines()
        replace_lines = [line for line in lines if "--replace" in line]
        # At least one line should be in a comment, echo, or usage function
        # (i.e., not only in the case statement)
        doc_lines = [
            line
            for line in replace_lines
            if "echo" in line or "Usage" in line or line.strip().startswith("#")
        ]
        assert len(doc_lines) > 0, (
            "--replace must be documented in usage/help text or a comment"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Contract tests — require real scripts and tools
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.requires_coq
class TestNightlyReindexContract:
    """Contract tests that verify real script behavior.

    These require the scripts to exist and external tools (docker, gh)
    to be available. Skipped in CI unless explicitly enabled.
    """

    @nightly_script_exists
    def test_nightly_script_syntax_check(self):
        """Contract: nightly-reindex.sh passes bash -n syntax check."""
        import subprocess

        result = subprocess.run(
            ["bash", "-n", str(NIGHTLY_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Syntax error in nightly-reindex.sh: {result.stderr}"
        )

    @cron_script_exists
    def test_cron_script_syntax_check(self):
        """Contract: reindex-cron.sh passes bash -n syntax check."""
        import subprocess

        result = subprocess.run(
            ["bash", "-n", str(CRON_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Syntax error in reindex-cron.sh: {result.stderr}"
        )
