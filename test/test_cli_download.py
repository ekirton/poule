"""Tests for poule.cli.download — CLI command to download prebuilt index.

Spec: specification/prebuilt-distribution.md §4.2–§4.7, §6
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

SAMPLE_MANIFEST = {
    "schema_version": "1",
    "coq_version": "8.19",
    "mathcomp_version": "2.2.0",
    "index_db_sha256": SAMPLE_DB_SHA256,
    "onnx_model_sha256": SAMPLE_ONNX_SHA256,
    "created_at": "2026-03-17T00:00:00Z",
}


def _make_release(tag: str = "index-v1-coq8.19-mc2.2.0") -> dict:
    """Create a fake GitHub release dict."""
    return {
        "tag_name": tag,
        "assets": [
            {
                "name": "manifest.json",
                "browser_download_url": "https://example.com/manifest.json",
                "url": "https://api.github.com/repos/ekirton/Poule/releases/assets/1",
            },
            {
                "name": "index.db",
                "browser_download_url": "https://example.com/index.db",
                "url": "https://api.github.com/repos/ekirton/Poule/releases/assets/2",
            },
            {
                "name": "neural-premise-selector.onnx",
                "browser_download_url": "https://example.com/model.onnx",
                "url": "https://api.github.com/repos/ekirton/Poule/releases/assets/3",
            },
        ],
    }


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
            _make_release("index-v1-coq8.19-mc2.2.0"),
            _make_release("index-v1-coq8.18-mc2.1.0"),
        ]
        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(releases).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            mock_open.return_value = resp
            result = _find_latest_release()
        assert result["tag_name"] == "index-v1-coq8.19-mc2.2.0"

    def test_selects_most_recent_among_multiple_index_releases(self):
        """§4.2: Given two index-v releases, returns the first (most recent)."""
        releases = [
            _make_release("index-v1-coq8.20-mc2.3.0"),
            _make_release("index-v1-coq8.19-mc2.2.0"),
        ]
        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(releases).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            mock_open.return_value = resp
            result = _find_latest_release()
        # API returns reverse chronological; first match is most recent
        assert result["tag_name"] == "index-v1-coq8.20-mc2.3.0"

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
        """§4.5: deletes file, message includes 'Expected {expected}, got {actual}. File deleted.'"""
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
        asset = _find_asset(release, "index.db")
        assert asset["name"] == "index.db"

    def test_missing_asset_raises_click_exception(self):
        """§6: 'Asset '{name}' not found in release '{tag}'.'"""
        release = _make_release("index-v1-coq8.19-mc2.2.0")
        import click
        with pytest.raises(click.ClickException, match="Asset 'missing.bin' not found") as exc_info:
            _find_asset(release, "missing.bin")
        assert "index-v1-coq8.19-mc2.2.0" in exc_info.value.message


# ===========================================================================
# 3. download-index CLI command — happy path
# ===========================================================================


class TestDownloadIndexCommand:
    """CLI download-index command end-to-end with mocked network."""

    def _invoke_download(self, runner, tmp_path, extra_args=None):
        """Invoke download-index with fully mocked network I/O."""
        output_path = tmp_path / "index.db"
        releases = [_make_release()]
        manifest_bytes = json.dumps(SAMPLE_MANIFEST).encode()

        url_map = {
            "https://example.com/manifest.json": manifest_bytes,
            "https://example.com/index.db": SAMPLE_DB_CONTENT,
            "https://example.com/model.onnx": SAMPLE_ONNX_CONTENT,
        }

        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            # First call: list releases; subsequent calls: download assets
            api_resp = MagicMock()
            api_resp.read.return_value = json.dumps(releases).encode()
            api_resp.__enter__ = lambda s: s
            api_resp.__exit__ = lambda s, *a: None

            mock_open.side_effect = _mock_urlopen(url_map)
            # Override the first call (API listing) to return releases JSON
            original_side_effect = mock_open.side_effect

            call_count = [0]
            def _routing_side_effect(req):
                call_count[0] += 1
                url = req.full_url if hasattr(req, "full_url") else str(req)
                if "api.github.com" in url:
                    resp = MagicMock()
                    resp.read.return_value = json.dumps(releases).encode()
                    resp.headers = {"Content-Length": "0"}
                    resp.__enter__ = lambda s: s
                    resp.__exit__ = lambda s, *a: None
                    return resp
                return original_side_effect(req)

            mock_open.side_effect = _routing_side_effect

            args = ["--output", str(output_path)]
            if extra_args:
                args.extend(extra_args)
            result = runner.invoke(download_index, args)

        return result, output_path

    def test_downloads_index_db(self, runner, tmp_path):
        result, output_path = self._invoke_download(runner, tmp_path)
        assert result.exit_code == 0, result.output
        assert output_path.exists()
        assert output_path.read_bytes() == SAMPLE_DB_CONTENT

    def test_prints_done_on_success(self, runner, tmp_path):
        result, _ = self._invoke_download(runner, tmp_path)
        assert result.exit_code == 0
        # "Done." is printed to stderr; CliRunner mixes output by default
        assert "Done" in result.output

    def test_include_model_downloads_onnx(self, runner, tmp_path):
        """§4.7: --include-model with ONNX in release → both downloaded."""
        model_dir = tmp_path / "models"
        result, _ = self._invoke_download(
            runner, tmp_path,
            extra_args=["--include-model", "--model-dir", str(model_dir)],
        )
        assert result.exit_code == 0, result.output
        model_path = model_dir / "neural-premise-selector.onnx"
        assert model_path.exists()
        assert model_path.read_bytes() == SAMPLE_ONNX_CONTENT

    def test_include_model_null_onnx_prints_warning_and_skips(self, runner, tmp_path):
        """§4.7: --include-model but onnx_model_sha256 is null → warning, skip, exit 0."""
        output_path = tmp_path / "index.db"
        model_dir = tmp_path / "models"
        manifest_no_onnx = {
            **SAMPLE_MANIFEST,
            "onnx_model_sha256": None,
        }
        releases = [_make_release()]
        manifest_bytes = json.dumps(manifest_no_onnx).encode()

        url_map = {
            "https://example.com/manifest.json": manifest_bytes,
            "https://example.com/index.db": SAMPLE_DB_CONTENT,
        }

        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
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
                ["--output", str(output_path), "--include-model", "--model-dir", str(model_dir)],
            )
        assert result.exit_code == 0, result.output
        assert "Warning" in result.output or "No ONNX model" in result.output
        assert not (model_dir / "neural-premise-selector.onnx").exists()


# ===========================================================================
# 4. download-index CLI command — error cases
# ===========================================================================


class TestDownloadIndexErrors:
    """download-index error handling."""

    def test_output_exists_without_force_exits_1(self, runner, tmp_path):
        """§6: '{path} already exists. Use --force to overwrite.'"""
        existing = tmp_path / "index.db"
        existing.write_text("existing")
        result = runner.invoke(download_index, ["--output", str(existing)])
        assert result.exit_code == 1
        assert "already exists" in result.output
        assert "--force to overwrite" in result.output

    def test_output_exists_with_force_proceeds(self, runner, tmp_path):
        existing = tmp_path / "index.db"
        existing.write_text("old")
        releases = [_make_release()]
        manifest_bytes = json.dumps(SAMPLE_MANIFEST).encode()

        url_map = {
            "https://example.com/manifest.json": manifest_bytes,
            "https://example.com/index.db": SAMPLE_DB_CONTENT,
        }

        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
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
                download_index, ["--output", str(existing), "--force"]
            )
        assert result.exit_code == 0, result.output
        assert existing.read_bytes() == SAMPLE_DB_CONTENT

    def test_model_exists_without_force_exits_1(self, runner, tmp_path):
        """§6: Model file exists, no --force → exit 1."""
        db_output = tmp_path / "index.db"
        model_dir = tmp_path / "models"
        model_dir.mkdir()
        (model_dir / "neural-premise-selector.onnx").write_text("existing")
        result = runner.invoke(
            download_index,
            ["--output", str(db_output), "--include-model", "--model-dir", str(model_dir)],
        )
        assert result.exit_code == 1
        assert "already exists" in result.output

    def test_no_release_found_exits_1(self, runner, tmp_path):
        """§6: No matching release → exit 1, 'No index release found on GitHub.'"""
        releases = [{"tag_name": "v0.1.0", "assets": []}]
        with patch("Poule.cli.download.urllib.request.urlopen") as mock_open:
            resp = MagicMock()
            resp.read.return_value = json.dumps(releases).encode()
            resp.__enter__ = lambda s: s
            resp.__exit__ = lambda s, *a: None
            mock_open.return_value = resp
            result = runner.invoke(
                download_index, ["--output", str(tmp_path / "index.db")]
            )
        assert result.exit_code == 1
        assert "No index release found on GitHub" in result.output

    def test_network_error_exits_1(self, runner, tmp_path):
        """§6: Network failure → exit 1, 'Failed to reach GitHub API: {details}'."""
        import urllib.error
        with patch(
            "Poule.cli.download.urllib.request.urlopen",
            side_effect=urllib.error.URLError("Connection refused"),
        ):
            result = runner.invoke(
                download_index, ["--output", str(tmp_path / "index.db")]
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
        assert "--output" in result.output
        assert "--include-model" in result.output
        assert "--model-dir" in result.output
        assert "--force" in result.output
