"""Tests for library version detection (specification/extraction.md §4.9).

Tests detect_library_version() which returns version strings for installed
Coq libraries using coqc --version (stdlib) or opam show (all others).
"""

from __future__ import annotations

from unittest.mock import Mock, patch

import pytest


class TestDetectLibraryVersionStdlib:
    """detect_library_version("stdlib") parses coqc --version output."""

    def test_stdlib_version_from_coqc(self):
        """§4.9: stdlib version parsed from 'coqc --version' output."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0,
                stdout="The Coq Proof Assistant, version 8.19.2\n",
            )
            result = detect_library_version("stdlib")

        assert result == "8.19.2"

    def test_stdlib_uses_coqc_not_opam(self):
        """§4.9: stdlib detection uses coqc --version, not opam show."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0,
                stdout="The Coq Proof Assistant, version 8.19.2\n",
            )
            detect_library_version("stdlib")

        # Verify coqc was called, not opam
        args_list = mock_sub.run.call_args_list
        assert len(args_list) >= 1
        first_call_args = args_list[0][0][0]  # positional arg 0 of first call
        assert "coqc" in first_call_args, (
            f"Expected coqc in command, got: {first_call_args}"
        )
        # Ensure opam was NOT called
        for call in args_list:
            cmd = call[0][0]
            assert "opam" not in cmd, (
                f"stdlib should not use opam, but found: {cmd}"
            )


class TestDetectLibraryVersionOpam:
    """detect_library_version for non-stdlib libraries uses opam show."""

    def test_mathcomp_version_from_opam(self):
        """§4.9: mathcomp version from opam show coq-mathcomp-ssreflect."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0,
                stdout="2.2.0\n",
            )
            result = detect_library_version("mathcomp")

        assert result == "2.2.0"
        cmd = mock_sub.run.call_args[0][0]
        assert "coq-mathcomp-ssreflect" in cmd

    def test_stdpp_version_from_opam(self):
        """§4.9: stdpp version from opam show coq-stdpp."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0,
                stdout="1.9.0\n",
            )
            result = detect_library_version("stdpp")

        assert result == "1.9.0"
        cmd = mock_sub.run.call_args[0][0]
        assert "coq-stdpp" in cmd

    def test_flocq_version_from_opam(self):
        """§4.9: flocq version from opam show coq-flocq."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0,
                stdout="4.1.4\n",
            )
            result = detect_library_version("flocq")

        assert result == "4.1.4"
        cmd = mock_sub.run.call_args[0][0]
        assert "coq-flocq" in cmd

    def test_coquelicot_version_from_opam(self):
        """§4.9: coquelicot version from opam show coq-coquelicot."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0,
                stdout="3.4.1\n",
            )
            result = detect_library_version("coquelicot")

        assert result == "3.4.1"
        cmd = mock_sub.run.call_args[0][0]
        assert "coq-coquelicot" in cmd

    def test_coqinterval_version_from_opam(self):
        """§4.9: coqinterval version from opam show coq-interval."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0,
                stdout="4.10.0\n",
            )
            result = detect_library_version("coqinterval")

        assert result == "4.10.0"
        cmd = mock_sub.run.call_args[0][0]
        assert "coq-interval" in cmd


class TestDetectLibraryVersionNotInstalled:
    """detect_library_version returns "none" when library is not installed."""

    def test_not_installed_returns_none(self):
        """§4.9: when opam show fails (library not installed), returns 'none'."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=1,
                stdout="",
            )
            result = detect_library_version("stdpp")

        assert result == "none"

    def test_not_installed_opam_not_found_returns_none(self):
        """§4.9: when opam binary is missing, returns 'none'."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.side_effect = FileNotFoundError("opam not found")
            result = detect_library_version("flocq")

        assert result == "none"

    def test_stdlib_not_installed_returns_none(self):
        """§4.9: when coqc is missing, returns 'none'."""
        from Poule.extraction.version_detection import detect_library_version

        with patch("Poule.extraction.version_detection.subprocess") as mock_sub:
            mock_sub.run.side_effect = FileNotFoundError("coqc not found")
            result = detect_library_version("stdlib")

        assert result == "none"


# ═══════════════════════════════════════════════════════════════════════════
# Contract tests — require real Coq installation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.requires_coq
class TestDetectLibraryVersionContract:
    """Contract tests verifying detect_library_version with real tools."""

    def test_stdlib_version_real(self):
        """Contract: detect_library_version("stdlib") returns a version string from real coqc."""
        from Poule.extraction.version_detection import detect_library_version

        result = detect_library_version("stdlib")
        assert result != "none", "Expected coqc to be installed for contract test"
        # Version should look like a semver-ish string
        parts = result.split(".")
        assert len(parts) >= 2, f"Expected version with dots, got: {result}"
        assert parts[0].isdigit(), f"Major version not numeric: {result}"

    def test_mathcomp_version_real(self):
        """Contract: detect_library_version("mathcomp") returns a version or 'none'."""
        from Poule.extraction.version_detection import detect_library_version

        result = detect_library_version("mathcomp")
        # Either a version string or "none" — both are valid
        assert isinstance(result, str)
        if result != "none":
            assert "." in result, f"Expected dotted version, got: {result}"

    def test_stdpp_version_real(self):
        """Contract: detect_library_version("stdpp") returns a version or 'none'."""
        from Poule.extraction.version_detection import detect_library_version

        result = detect_library_version("stdpp")
        assert isinstance(result, str)
        if result != "none":
            assert "." in result, f"Expected dotted version, got: {result}"
