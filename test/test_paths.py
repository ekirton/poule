"""Tests for poule.paths — platform-specific data directory helpers.

Spec: specification/prebuilt-distribution.md §4.1

Import paths under test:
  poule.paths.get_data_dir
  poule.paths.get_model_dir
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from Poule.paths import get_data_dir, get_model_dir


# ===========================================================================
# get_data_dir
# ===========================================================================


class TestGetDataDir:
    """get_data_dir returns platform-specific data directory."""

    def test_macos_returns_library_application_support(self):
        with patch("Poule.paths.sys") as mock_sys:
            mock_sys.platform = "darwin"
            result = get_data_dir()
        assert result == Path.home() / "Library" / "Application Support" / "poule"

    def test_linux_returns_local_share(self):
        with patch("Poule.paths.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = get_data_dir()
        assert result == Path.home() / ".local" / "share" / "poule"

    def test_unknown_platform_falls_back_to_linux_convention(self):
        with patch("Poule.paths.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            result = get_data_dir()
        assert result == Path.home() / ".local" / "share" / "poule"

    def test_returns_path_object(self):
        result = get_data_dir()
        assert isinstance(result, Path)

    def test_does_not_create_directory(self, tmp_path):
        """get_data_dir must NOT create directories — that's the caller's job."""
        with patch("Poule.paths.sys") as mock_sys, \
             patch("Poule.paths.Path.home", return_value=tmp_path):
            mock_sys.platform = "linux"
            result = get_data_dir()
        # The directory should not have been created
        assert not result.exists()


# ===========================================================================
# get_model_dir
# ===========================================================================


class TestGetModelDir:
    """get_model_dir returns get_data_dir() / 'models'."""

    def test_is_subdirectory_of_data_dir(self):
        result = get_model_dir()
        assert result == get_data_dir() / "models"

    def test_macos_model_dir(self):
        with patch("Poule.paths.sys") as mock_sys:
            mock_sys.platform = "darwin"
            result = get_model_dir()
        assert result == Path.home() / "Library" / "Application Support" / "poule" / "models"

    def test_linux_model_dir(self):
        with patch("Poule.paths.sys") as mock_sys:
            mock_sys.platform = "linux"
            result = get_model_dir()
        assert result == Path.home() / ".local" / "share" / "poule" / "models"

    def test_returns_path_object(self):
        result = get_model_dir()
        assert isinstance(result, Path)

    def test_does_not_create_directory(self, tmp_path):
        """get_model_dir must NOT create directories — that's the caller's job."""
        with patch("Poule.paths.sys") as mock_sys, \
             patch("Poule.paths.Path.home", return_value=tmp_path):
            mock_sys.platform = "linux"
            result = get_model_dir()
        assert not result.exists()
