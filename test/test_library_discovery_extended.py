"""Tests for extended library discovery (specification/extraction.md §4.8).

Tests the 4 new library targets added to discover_libraries():
stdpp, flocq, coquelicot, coqinterval.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest


class TestDiscoverLibrariesExtended:
    """discover_libraries supports stdpp, flocq, coquelicot, coqinterval."""

    def test_stdpp_discovers_vo_files(self, tmp_path):
        """§4.8: discover_libraries("stdpp") returns .vo files from user-contrib/stdpp/."""
        from Poule.extraction.pipeline import discover_libraries

        stdpp = tmp_path / "user-contrib" / "stdpp"
        stdpp.mkdir(parents=True)
        (stdpp / "base.vo").touch()
        (stdpp / "tactics.vo").touch()
        (stdpp / "base.glob").touch()  # non-.vo file, should be ignored

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            result = discover_libraries("stdpp")

        assert len(result) == 2
        assert all(str(p).endswith(".vo") for p in result)

    def test_flocq_discovers_vo_files(self, tmp_path):
        """§4.8: discover_libraries("flocq") returns .vo files from user-contrib/Flocq/."""
        from Poule.extraction.pipeline import discover_libraries

        flocq = tmp_path / "user-contrib" / "Flocq"
        flocq.mkdir(parents=True)
        (flocq / "Core").mkdir()
        (flocq / "Core" / "Raux.vo").touch()
        (flocq / "Core" / "Defs.vo").touch()
        (flocq / "Calc").mkdir()
        (flocq / "Calc" / "Bracket.vo").touch()

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            result = discover_libraries("flocq")

        assert len(result) == 3
        assert all(str(p).endswith(".vo") for p in result)

    def test_coquelicot_discovers_vo_files(self, tmp_path):
        """§4.8: discover_libraries("coquelicot") returns .vo files from user-contrib/Coquelicot/."""
        from Poule.extraction.pipeline import discover_libraries

        coquelicot = tmp_path / "user-contrib" / "Coquelicot"
        coquelicot.mkdir(parents=True)
        (coquelicot / "Coquelicot.vo").touch()
        (coquelicot / "Hierarchy.vo").touch()

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            result = discover_libraries("coquelicot")

        assert len(result) == 2
        assert all(str(p).endswith(".vo") for p in result)

    def test_coqinterval_discovers_vo_files(self, tmp_path):
        """§4.8: discover_libraries("coqinterval") returns .vo from user-contrib/Interval/.

        Note: directory name (Interval) differs from identifier (coqinterval).
        """
        from Poule.extraction.pipeline import discover_libraries

        interval = tmp_path / "user-contrib" / "Interval"
        interval.mkdir(parents=True)
        (interval / "Tactic.vo").touch()
        (interval / "Float").mkdir()
        (interval / "Float" / "Specific_ops.vo").touch()

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            result = discover_libraries("coqinterval")

        assert len(result) == 2
        assert all(str(p).endswith(".vo") for p in result)

    def test_unknown_target_raises_error(self):
        """§4.8: unrecognized target that is not a filesystem path raises ExtractionError."""
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import discover_libraries

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout="/fake/coq/lib\n"
            )
            with pytest.raises(ExtractionError):
                discover_libraries("badlib")

    def test_unknown_target_error_lists_valid_identifiers(self):
        """§4.8: error message includes all 6 valid identifiers."""
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import discover_libraries

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout="/fake/coq/lib\n"
            )
            with pytest.raises(ExtractionError, match="stdlib") as exc_info:
                discover_libraries("badlib")

        msg = str(exc_info.value)
        for lib in ["stdlib", "mathcomp", "stdpp", "flocq", "coquelicot", "coqinterval"]:
            assert lib in msg, f"Error message missing valid identifier '{lib}': {msg}"

    def test_no_vo_files_raises_error(self, tmp_path):
        """§4.8: valid target but empty directory raises ExtractionError."""
        from Poule.extraction.errors import ExtractionError
        from Poule.extraction.pipeline import discover_libraries

        # Create the expected directory but leave it empty (no .vo files)
        stdpp = tmp_path / "user-contrib" / "stdpp"
        stdpp.mkdir(parents=True)

        with patch("Poule.extraction.pipeline.subprocess") as mock_sub:
            mock_sub.run.return_value = Mock(
                returncode=0, stdout=str(tmp_path) + "\n"
            )
            with pytest.raises(ExtractionError):
                discover_libraries("stdpp")


# ═══════════════════════════════════════════════════════════════════════════
# Contract tests — require real Coq installation
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.requires_coq
class TestDiscoverLibrariesExtendedContract:
    """Contract tests verifying real library discovery against installed Coq."""

    def test_stdpp_real_discovery(self):
        """Contract: discover_libraries("stdpp") works with real coqc -where."""
        from Poule.extraction.pipeline import discover_libraries

        try:
            result = discover_libraries("stdpp")
            assert all(str(p).endswith(".vo") for p in result)
            assert len(result) > 0
        except Exception:
            pytest.skip("stdpp not installed")

    def test_flocq_real_discovery(self):
        """Contract: discover_libraries("flocq") works with real coqc -where."""
        from Poule.extraction.pipeline import discover_libraries

        try:
            result = discover_libraries("flocq")
            assert all(str(p).endswith(".vo") for p in result)
            assert len(result) > 0
        except Exception:
            pytest.skip("flocq not installed")

    def test_coquelicot_real_discovery(self):
        """Contract: discover_libraries("coquelicot") works with real coqc -where."""
        from Poule.extraction.pipeline import discover_libraries

        try:
            result = discover_libraries("coquelicot")
            assert all(str(p).endswith(".vo") for p in result)
            assert len(result) > 0
        except Exception:
            pytest.skip("coquelicot not installed")

    def test_coqinterval_real_discovery(self):
        """Contract: discover_libraries("coqinterval") works with real coqc -where."""
        from Poule.extraction.pipeline import discover_libraries

        try:
            result = discover_libraries("coqinterval")
            assert all(str(p).endswith(".vo") for p in result)
            assert len(result) > 0
        except Exception:
            pytest.skip("coqinterval not installed")
