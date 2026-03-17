"""CLI command to download prebuilt index from GitHub Releases."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import click

from poule.paths import get_model_dir

GITHUB_API_URL = "https://api.github.com/repos/ekirton/poule/releases"
TAG_PREFIX = "index-v"
CHUNK_SIZE = 65536  # 64 KB


def _find_latest_release() -> dict:
    """Find the most recent GitHub Release with an index tag."""
    req = urllib.request.Request(
        GITHUB_API_URL,
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            releases = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise click.ClickException(f"Failed to reach GitHub API: {exc}") from exc

    for release in releases:
        if release.get("tag_name", "").startswith(TAG_PREFIX):
            return release

    raise click.ClickException("No index release found on GitHub.")


def _find_asset(release: dict, name: str) -> dict:
    """Find an asset by name within a release."""
    for asset in release.get("assets", []):
        if asset["name"] == name:
            return asset
    raise click.ClickException(
        f"Asset '{name}' not found in release '{release['tag_name']}'."
    )


def _download_file(url: str, dest: Path, label: str) -> None:
    """Download a file with progress reporting to stderr."""
    tmp_path = dest.with_suffix(dest.suffix + ".tmp")
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            total_mb = total / (1024 * 1024) if total else 0
            downloaded = 0

            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        mb = downloaded / (1024 * 1024)
                        click.echo(
                            f"\r  Downloading {label} ... "
                            f"{mb:.1f} / {total_mb:.1f} MB",
                            nl=False,
                            err=True,
                        )
            if total:
                click.echo("", err=True)  # newline after progress
    except urllib.error.URLError as exc:
        tmp_path.unlink(missing_ok=True)
        raise click.ClickException(f"Download failed for {label}: {exc}") from exc
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    return tmp_path


def _verify_checksum(path: Path, expected_sha256: str, label: str) -> None:
    """Verify SHA-256 checksum of a downloaded file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            sha256.update(chunk)
    actual = sha256.hexdigest()
    if actual != expected_sha256:
        path.unlink(missing_ok=True)
        raise click.ClickException(
            f"Checksum verification failed for {label}. "
            f"Expected {expected_sha256}, got {actual}. File deleted."
        )


def _download_and_verify(
    release: dict, asset_name: str, dest: Path, checksum: str, label: str
) -> None:
    """Download an asset, verify its checksum, and atomically place it."""
    asset = _find_asset(release, asset_name)
    url = asset["browser_download_url"]
    tmp_path = _download_file(url, dest, label)
    _verify_checksum(tmp_path, checksum, label)
    os.replace(tmp_path, dest)
    size_mb = dest.stat().st_size / (1024 * 1024)
    click.echo(f"  {label} ({size_mb:.1f} MB) -> {dest}", err=True)


@click.command("download-index")
@click.option(
    "--output",
    type=click.Path(path_type=Path),
    default=Path("index.db"),
    help="Where to save the database file.",
    show_default=True,
)
@click.option(
    "--include-model",
    is_flag=True,
    default=False,
    help="Also download the ONNX neural premise selection model.",
)
@click.option(
    "--model-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Where to save the ONNX model. Defaults to platform data directory.",
)
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Overwrite existing files without prompting.",
)
def download_index(
    output: Path, include_model: bool, model_dir: Path | None, force: bool
) -> None:
    """Download the prebuilt search index from GitHub Releases."""
    if model_dir is None:
        model_dir = get_model_dir()

    # Check for existing files before downloading anything
    if output.exists() and not force:
        raise click.ClickException(
            f"{output} already exists. Use --force to overwrite."
        )

    model_path = model_dir / "neural-premise-selector.onnx"
    if include_model and model_path.exists() and not force:
        raise click.ClickException(
            f"{model_path} already exists. Use --force to overwrite."
        )

    # Resolve latest release
    click.echo("Finding latest index release...", err=True)
    release = _find_latest_release()
    tag = release["tag_name"]
    click.echo(f"Found release: {tag}", err=True)

    # Download and parse manifest
    manifest_asset = _find_asset(release, "manifest.json")
    req = urllib.request.Request(manifest_asset["browser_download_url"])
    try:
        with urllib.request.urlopen(req) as resp:
            manifest = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise click.ClickException(
            f"Failed to download manifest: {exc}"
        ) from exc

    # Download index.db
    _download_and_verify(
        release, "index.db", output, manifest["index_db_sha256"], "index.db"
    )

    # Download ONNX model if requested
    if include_model:
        onnx_checksum = manifest.get("onnx_model_sha256")
        if not onnx_checksum:
            click.echo(
                "  Warning: No ONNX model in this release. Skipping.", err=True
            )
        else:
            model_dir.mkdir(parents=True, exist_ok=True)
            _download_and_verify(
                release,
                "neural-premise-selector.onnx",
                model_path,
                onnx_checksum,
                "neural-premise-selector.onnx",
            )

    click.echo("Done.", err=True)
