"""Tests for poule.cli.download — CLI command to download prebuilt index.

Spec: specification/prebuilt-distribution.md §4.2–§4.9, §6
      specification/cli.md §4.16

Import paths under test:
  poule.cli.download.download_index
  poule.cli.download._find_latest_release
  poule.cli.download._find_asset
  poule.cli.download._verify_checksum
"""

from __future__ import annotations

import hashlib
import json
import os
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from Poule.cli.download import (
    _find_asset,
    _find_latest_release,
    _verify_checksum,
    download_index,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

SAMPLE_DB_CONTENT = b"fake-sqlite-content-for-testing"
SAMPLE_DB_SHA256 = hashlib.sha256(SAMPLE_DB_CONTENT).hexdigest()

SAMPLE_ONNX_CONTENT = b"fake-onnx-model-bytes"
SAMPLE_ONNX_SHA256 = hashlib.sha256(SAMPLE_ONNX_CONTENT).hexdigest()

ALL_LIBRARIES = ["stdlib", "stdpp", "mathcomp", "flocq", "coqinterval", "coquelicot"]

# Generate sample content and checksums for each library
SAMPLE_LIB_CONTENT = {}
SAMPLE_LIB_SHA256 = {}
for _lib in ALL_LIBRARIES:
    content = f"fake-{_lib}-index-content".encode()
    SAMPLE_LIB_CONTENT[_lib] = content
    SAMPLE_LIB_SHA256[_lib] = hashlib.sha256(content).hexdigest()

# Keep backward-compatible aliases used by existing tests
SAMPLE_STDLIB_CONTENT = SAMPLE_LIB_CONTENT["stdlib"]
SAMPLE_STDLIB_SHA256 = SAMPLE_LIB_SHA256["stdlib"]
SAMPLE_MATHCOMP_CONTENT = SAMPLE_LIB_CONTENT["mathcomp"]
SAMPLE_MATHCOMP_SHA256 = SAMPLE_LIB_SHA256["mathcomp"]

SAMPLE_MANIFEST = {
    "schema_version": "1",
    "coq_version": "8.19",
    "libraries": {
        lib: {
            "version": f"{i}.0.0",
            "sha256": SAMPLE_LIB_SHA256[lib],
            "asset_name": f"index-{lib}.db",
            "declarations": 1000 * (i + 1),
        }
        for i, lib in enumerate(ALL_LIBRARIES)
    },
    "onnx_model_sha256": SAMPLE_ONNX_SHA256,
    "created_at": "2026-03-18T00:00:00Z",
}


def _make_release(tag: str = "index-v1-coq8.19") -> dict:
    """Create a fake GitHub release dict."""
    assets = [
        {
            "name": "manifest.json",
            "browser_download_url": "https://example.com/manifest.json",
            "url": "https://api.github.com/repos/ekirton/Poule/releases/assets/1",
        },
    ]
    for i, lib in enumerate(ALL_LIBRARIES):
        assets.append({
            "name": f"index-{lib}.db",
            "browser_download_url": f"https://example.com/index-{lib}.db",
            "url": f"https://api.github.com/repos/ekirton/Poule/releases/assets/{i + 2}",
        })
    assets.append({
        "name": "neural-premise-selector.onnx",
        "browser_download_url": "https://example.com/model.onnx",
        "url": f"https://api.github.com/repos/ekirton/Poule/releases/assets/{len(ALL_LIBRARIES) + 2}",
    })
    return {"tag_name": tag, "assets": assets}


def _mock_urlopen(url_to_content: dict):
    """Return a side_effect function for urllib.request.urlopen.

    url_to_content maps URL strings to bytes content.
    """
    def _side_effect(req):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        content = url_to_content.get(url, b"")
        resp = MagicMock()
        resp.read = BytesIO(content).read
        resp.headers = {"Content-Length": str(len(content))}
        resp.__enter__ = lambda s: s
        resp.__exit__ = lambda s, *a: None
        return resp
    return _side_effect


@pytest.fixture
def runner():
    return CliRunner()


# ===========================================================================
# 1. _find_latest_release
# ===========================================================================


class TestFindLatestRelease:
    """_find_latest_release resolves the most recent index-v* release."""

    def test_returns_first_matching_release(self):
        releases = [
            {"tag_name": "v0.1.0", "assets": []},
            _make_release("index-v1-coq8.19"),
            _make_release("index-v1-coq8.18"),
        ]
        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(releases).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            mock_open.return_value = resp
            result = _find_latest_release()
        assert result["tag_name"] == "index-v1-coq8.19"

    def test_selects_most_recent_among_multiple_index_releases(self):
        """§4.3: Given two index-v releases, returns the first (most recent)."""
        releases = [
            _make_release("index-v1-coq8.20"),
            _make_release("index-v1-coq8.19"),
        ]
        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(releases).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            mock_open.return_value = resp
            result = _find_latest_release()
        # API returns reverse chronological; first match is most recent
        assert result["tag_name"] == "index-v1-coq8.20"

    def test_no_matching_release_raises_click_exception(self):
        releases = [{"tag_name": "v0.1.0", "assets": []}]
        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(releases).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            mock_open.return_value = resp
            import click
            with pytest.raises(click.ClickException, match="No index release found"):
                _find_latest_release()

    def test_network_error_raises_click_exception(self):
        import urllib.error
        with patch(
            "Poule.cli.download.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            import click
            with pytest.raises(click.ClickException, match="Failed to reach GitHub API"):
                _find_latest_release()


# ===========================================================================
# 2. _verify_checksum
# ===========================================================================


class TestVerifyChecksum:
    """_verify_checksum validates SHA-256 and deletes on mismatch."""

    def test_matching_checksum_passes(self, tmp_path):
        f = tmp_path / "test.db"
        f.write_bytes(SAMPLE_DB_CONTENT)
        # Should not raise
        _verify_checksum(f, SAMPLE_DB_SHA256, "test.db")
        assert f.exists()

    def test_mismatched_checksum_deletes_and_raises(self, tmp_path):
        """§4.6: deletes file, message includes 'Expected {expected}, got {actual}. File deleted.'"""
        wrong_content = b"wrong content"
        wrong_sha = hashlib.sha256(wrong_content).hexdigest()
        f = tmp_path / "test.db"
        f.write_bytes(wrong_content)
        import click
        with pytest.raises(click.ClickException, match="Checksum verification failed") as exc_info:
            _verify_checksum(f, SAMPLE_DB_SHA256, "test.db")
        msg = exc_info.value.message
        assert f"Expected {SAMPLE_DB_SHA256}" in msg
        assert f"got {wrong_sha}" in msg
        assert "File deleted" in msg
        assert not f.exists()


# ===========================================================================
# 2b. _find_asset
# ===========================================================================


class TestFindAsset:
    """_find_asset locates an asset by name within a release."""

    def test_returns_matching_asset(self):
        release = _make_release()
        asset = _find_asset(release, "index-stdlib.db")
        assert asset["name"] == "index-stdlib.db"

    def test_missing_asset_raises_click_exception(self):
        """§6: 'Asset '{name}' not found in release '{tag}'.'"""
        release = _make_release("index-v1-coq8.19")
        import click
        with pytest.raises(click.ClickException, match="Asset 'missing.bin' not found") as exc_info:
            _find_asset(release, "missing.bin")
        assert "index-v1-coq8.19" in exc_info.value.message


# ===========================================================================
# 3. download-index CLI command — happy path
# ===========================================================================


class TestDownloadIndexCommand:
    """CLI download-index command end-to-end with mocked network."""

    def _invoke_download(self, runner, tmp_path, extra_args=None):
        """Invoke download-index with fully mocked network I/O."""
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()

        releases = [_make_release()]
        manifest_bytes = json.dumps(SAMPLE_MANIFEST).encode()

        url_map = {
            "https://example.com/manifest.json": manifest_bytes,
            "https://example.com/model.onnx": SAMPLE_ONNX_CONTENT,
        }
        for lib in ALL_LIBRARIES:
            url_map[f"https://example.com/index-{lib}.db"] = SAMPLE_LIB_CONTENT[lib]

        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open, \
             patch("Poule.cli.download.merge_indexes", return_value={
                 "total_declarations": 100,
                 "total_dependencies": 50,
                 "dropped_dependencies": 0,
                 "libraries": ALL_LIBRARIES,
             }) as mock_merge:
            def _routing_side_effect(req):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if "api.github.com" in url:
                    resp = MagicMock()
                    resp.read.return_value = json.dumps(releases).encode()
                    resp.headers = {"Content-Length": "0"}
                    resp.__enter__ = lambda s: s
                    resp.__exit__ = lambda s, *a: None
                    return resp
                content = url_map.get(url, b"")
                resp = MagicMock()
                resp.read = BytesIO(content).read
                resp.headers = {"Content-Length": str(len(content))}
                resp.__enter__ = lambda s: s
                resp.__exit__ = lambda s, *a: None
                return resp

            mock_open.side_effect = _routing_side_effect

            args = ["--libraries-dir", str(libs_dir)]
            if extra_args:
                args.extend(extra_args)
            result = runner.invoke(download_index, args)

        return result, libs_dir, mock_merge

    def test_downloads_per_library_indexes(self, runner, tmp_path):
        """§4.9: Downloads all 6 per-library index files to libraries dir."""
        result, libs_dir, _ = self._invoke_download(runner, tmp_path)
        assert result.exit_code == 0, result.output
        for lib in ALL_LIBRARIES:
            assert (libs_dir / f"index-{lib}.db").exists()

    def test_calls_merge_indexes(self, runner, tmp_path):
        """§4.9: After download, merge_indexes is called."""
        result, libs_dir, mock_merge = self._invoke_download(runner, tmp_path)
        assert result.exit_code == 0, result.output
        mock_merge.assert_called_once()

    def test_prints_done_on_success(self, runner, tmp_path):
        """§4.9: Prints summary on success."""
        result, _, _ = self._invoke_download(runner, tmp_path)
        assert result.exit_code == 0
        assert "Done" in result.output

    def test_include_model_downloads_onnx(self, runner, tmp_path):
        """§4.7: --include-model with ONNX in release → both downloaded."""
        model_dir = tmp_path / "models"
        result, _, _ = self._invoke_download(
            runner, tmp_path,
            extra_args=["--include-model", "--model-dir", str(model_dir)],
        )
        assert result.exit_code == 0, result.output
        model_path = model_dir / "neural-premise-selector.onnx"
        assert model_path.exists()
        assert model_path.read_bytes() == SAMPLE_ONNX_CONTENT

    def test_include_model_null_onnx_prints_warning_and_skips(self, runner, tmp_path):
        """§4.7: --include-model but onnx_model_sha256 is null → warning, skip, exit 0."""
        model_dir = tmp_path / "models"
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()
        manifest_no_onnx = {
            **SAMPLE_MANIFEST,
            "onnx_model_sha256": None,
        }
        releases = [_make_release()]
        manifest_bytes = json.dumps(manifest_no_onnx).encode()

        url_map = {
            "https://example.com/manifest.json": manifest_bytes,
        }
        for lib in ALL_LIBRARIES:
            url_map[f"https://example.com/index-{lib}.db"] = SAMPLE_LIB_CONTENT[lib]

        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open, \
             patch("Poule.cli.download.merge_indexes", return_value={
                 "total_declarations": 100,
                 "total_dependencies": 50,
                 "dropped_dependencies": 0,
                 "libraries": ALL_LIBRARIES,
             }):
            def _routing(req):
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if "api.github.com" in url:
                    resp = MagicMock()
                    resp.read.return_value = json.dumps(releases).encode()
                    resp.headers = {"Content-Length": "0"}
                    resp.__enter__ = lambda s: s
                    resp.__exit__ = lambda s, *a: None
                    return resp
                content = url_map.get(url, b"")
                resp = MagicMock()
                resp.read = BytesIO(content).read
                resp.headers = {"Content-Length": str(len(content))}
                resp.__enter__ = lambda s: s
                resp.__exit__ = lambda s, *a: None
                return resp
            mock_open.side_effect = _routing
            result = runner.invoke(
                download_index,
                ["--libraries-dir", str(libs_dir), "--include-model", "--model-dir", str(model_dir)],
            )
        assert result.exit_code == 0, result.output
        assert "Warning" in result.output or "No ONNX model" in result.output
        assert not (model_dir / "neural-premise-selector.onnx").exists()


# ===========================================================================
# 4. download-index CLI command — error cases
# ===========================================================================


class TestDownloadIndexErrors:
    """download-index error handling."""

    def test_model_exists_without_force_exits_1(self, runner, tmp_path):
        """§6: Model file exists, no --force → exit 1."""
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()
        config = libs_dir / "config.toml"
        config.write_text('[index]\nlibraries = ["stdlib"]\n')
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        (model_dir / "neural-premise-selector.onnx").write_text("existing")
        result = runner.invoke(
            download_index,
            ["--libraries-dir", str(libs_dir), "--include-model", "--model-dir", str(model_dir)],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_no_release_found_exits_1(self, runner, tmp_path):
        """§6: No matching release → exit 1, 'No index release found on GitHub.'"""
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()
        releases = [{"tag_name": "v0.1.0", "assets": []}]
        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(releases).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            mock_open.return_value = resp
            result = runner.invoke(
                download_index, ["--libraries-dir", str(libs_dir)]
            )
        assert result.exit_code == 1
        assert "No index release found on GitHub" in result.output

    def test_network_error_exits_1(self, runner, tmp_path):
        """§6: Network failure → exit 1, 'Failed to reach GitHub API: {details}'."""
        libs_dir = tmp_path / "libraries"
        libs_dir.mkdir()
        import urllib.error
        with patch(
            "Poule.cli.download.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = runner.invoke(
                download_index, ["--libraries-dir", str(libs_dir)]
            )
        assert result.exit_code == 1
        assert "Failed to reach GitHub API" in result.output


# ===========================================================================
# 5. download-index --help
# ===========================================================================


class TestDownloadIndexHelp:
    """download-index --help prints usage."""

    def test_help_exits_0(self, runner):
        result = runner.invoke(download_index, ["--help"])
        assert result.exit_code == 0
        assert "download" in result.output.lower()

    def test_help_shows_all_options(self, runner):
        result = runner.invoke(download_index, ["--help"])
        assert "--libraries-dir" in result.output
        assert "--include-model" in result.output
        assert "--model-dir" in result.output
        assert "--force" in result.output
