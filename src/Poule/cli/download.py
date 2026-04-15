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

from Poule.paths import get_model_dir
from Poule.storage.merge import merge_indexes

GITHUB_API_URL = "https://api.github.com/repos/ekirton/Poule/releases"
TAG_LIBRARIES = "index-libraries"
TAG_MERGED = "index-merged"
TAG_MODEL = "tactic-model"
CHUNK_SIZE = 65536  # 64 KB
ALL_LIBRARIES = ["stdlib", "stdpp", "mathcomp", "flocq", "coqinterval", "coquelicot"]
MODEL_ARTIFACTS = ["tactic-predictor.onnx", "tactic-labels.json", "tokenizer.model"]


def get_libraries_dir() -> Path:
    """Return the libraries directory from env or default."""
    env = os.environ.get("POULE_LIBRARIES_PATH")
    if env:
        return Path(env)
    from Poule.paths import get_data_dir
    return get_data_dir()


def _find_latest_release() -> dict:
    """Find the most recent GitHub Release with an index tag.

    Scans all releases for a tag starting with ``index-``.
    Kept for backward compatibility with tests; new code should
    use :func:`_find_release` with an explicit tag.
    """
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
        tag = release.get("tag_name", "")
        if tag.startswith("index-"):
            return release

    raise click.ClickException("No index release found on GitHub.")


def _find_release(tag: str) -> dict:
    """Find a GitHub Release by exact tag name."""
    url = f"{GITHUB_API_URL}/tags/{tag}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise click.ClickException(
                f"No release found with tag '{tag}'."
            ) from exc
        raise click.ClickException(f"Failed to reach GitHub API: {exc}") from exc
    except urllib.error.URLError as exc:
        raise click.ClickException(f"Failed to reach GitHub API: {exc}") from exc


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


def _file_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            sha256.update(chunk)
    return sha256.hexdigest()


@click.command("download-index")
@click.option(
    "--libraries-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Libraries directory for config and per-library indexes.",
)
@click.option(
    "--include-model",
    is_flag=True,
    default=False,
    help="Also download the ONNX tactic prediction model.",
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
    libraries_dir: Path | None,
    include_model: bool,
    model_dir: Path | None,
    force: bool,
) -> None:
    """Download the prebuilt search index from GitHub Releases."""
    # 1. Resolve directories
    if libraries_dir is None:
        libraries_dir = get_libraries_dir()
    libraries_dir.mkdir(parents=True, exist_ok=True)

    if model_dir is None:
        model_dir = get_model_dir()

    # 2. Libraries are fixed
    libraries = list(ALL_LIBRARIES)

    # 3. Check for existing model before downloading anything
    model_path = model_dir / "tactic-predictor.onnx"
    if include_model and not force:
        existing = [model_dir / a for a in MODEL_ARTIFACTS if (model_dir / a).exists()]
        if existing:
            click.echo(
                "  Model artifacts already present. Will skip unchanged files "
                "(use --force to overwrite all).",
                err=True,
            )

    # 4. Resolve libraries release
    click.echo("Finding index release...", err=True)
    release = _find_latest_release()
    tag = release["tag_name"]
    click.echo(f"Found release: {tag}", err=True)

    # 5. Download and parse manifest
    manifest_asset = _find_asset(release, "manifest.json")
    req = urllib.request.Request(manifest_asset["browser_download_url"])
    try:
        with urllib.request.urlopen(req) as resp:
            manifest = json.loads(resp.read().decode())
    except urllib.error.URLError as exc:
        raise click.ClickException(
            f"Failed to download manifest: {exc}"
        ) from exc

    # 6. Download per-library index files
    for lib in libraries:
        lib_entry = manifest["libraries"].get(lib)
        if lib_entry is None:
            click.echo(f"  Warning: library '{lib}' not in manifest. Skipping.", err=True)
            continue

        asset_name = lib_entry["asset_name"]
        expected_sha = lib_entry["sha256"]
        dest = libraries_dir / asset_name

        # Skip if already downloaded with matching checksum
        if dest.exists():
            if _file_sha256(dest) == expected_sha:
                click.echo(f"  {asset_name} already up to date. Skipping.", err=True)
                continue

        _download_and_verify(release, asset_name, dest, expected_sha, asset_name)

    # 7. Merge per-library indexes into a single index.db
    sources = []
    for lib in libraries:
        lib_entry = manifest["libraries"].get(lib)
        if lib_entry is None:
            continue
        lib_path = libraries_dir / lib_entry["asset_name"]
        if lib_path.exists():
            sources.append((lib, lib_path))

    merged_dest = libraries_dir / "index.db"
    merge_indexes(sources, merged_dest)

    # 8. Handle ONNX model if requested — fetched from the tactic-model release
    if include_model:
        click.echo("Finding model release...", err=True)
        try:
            model_release = _find_release(TAG_MODEL)
        except click.ClickException:
            click.echo(
                "  Warning: No tactic-model release found. Skipping model download.",
                err=True,
            )
            model_release = None

        if model_release is not None:
            # Download and parse model manifest
            model_manifest_asset = _find_asset(model_release, "manifest.json")
            req = urllib.request.Request(
                model_manifest_asset["browser_download_url"]
            )
            try:
                with urllib.request.urlopen(req) as resp:
                    model_manifest = json.loads(resp.read().decode())
            except urllib.error.URLError as exc:
                raise click.ClickException(
                    f"Failed to download model manifest: {exc}"
                ) from exc

            model_dir.mkdir(parents=True, exist_ok=True)
            artifacts = model_manifest.get("artifacts", {})
            for artifact_name in MODEL_ARTIFACTS:
                entry = artifacts.get(artifact_name)
                if entry is None:
                    click.echo(
                        f"  Warning: {artifact_name} not in model manifest. Skipping.",
                        err=True,
                    )
                    continue
                dest = model_dir / artifact_name
                if dest.exists() and not force:
                    if _file_sha256(dest) == entry["sha256"]:
                        click.echo(
                            f"  {artifact_name} already up to date. Skipping.",
                            err=True,
                        )
                        continue
                _download_and_verify(
                    model_release,
                    artifact_name,
                    dest,
                    entry["sha256"],
                    artifact_name,
                )

    # 9. Done
    click.echo("Done.", err=True)
