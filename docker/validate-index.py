#!/usr/bin/env python3
"""Download index.db from GitHub Releases and validate against installed packages."""
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request

REPO = "ekirton/Poule"
TAG = "index-merged"


def fetch_json(url):
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def download(url, dest):
    urllib.request.urlretrieve(url, dest)


def main():
    # ── Fetch release metadata ────────────────────────────────────────────────
    release_url = f"https://api.github.com/repos/{REPO}/releases/tags/{TAG}"
    print(f"Downloading manifest from {TAG} release...")
    release = fetch_json(release_url)

    assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}

    if "manifest.json" not in assets:
        print("ERROR: manifest.json not found in release", file=sys.stderr)
        sys.exit(1)
    if "index.db" not in assets:
        print("ERROR: index.db not found in release", file=sys.stderr)
        sys.exit(1)

    # ── Download manifest and index ───────────────────────────────────────────
    download(assets["manifest.json"], "/tmp/manifest.json")
    manifest = json.load(open("/tmp/manifest.json"))

    print("Downloading index.db...")
    download(assets["index.db"], "/data/index.db")

    # ── Download FAISS sidecar (optional) ─────────────────────────────────────
    if "index.faiss" in assets:
        print("Downloading index.faiss...")
        download(assets["index.faiss"], "/data/index.faiss")
    else:
        print("No index.faiss in release (neural embeddings not yet computed).")

    # ── SHA-256 verification ──────────────────────────────────────────────────
    expected = manifest["index"]["sha256"]
    sha = hashlib.sha256(open("/data/index.db", "rb").read()).hexdigest()
    if sha != expected:
        print(f"SHA-256 mismatch: expected {expected}, got {sha}", file=sys.stderr)
        sys.exit(1)
    print(f"SHA-256 verified: {sha}")

    # ── Coq version ──────────────────────────────────────────────────────────
    result = subprocess.run(["coqc", "--version"], capture_output=True, text=True)
    m = re.search(r"version\s+([\d.]+)", result.stdout)
    if not m:
        print("ERROR: could not determine Coq version from coqc", file=sys.stderr)
        sys.exit(1)
    installed_coq = m.group(1)
    manifest_coq = manifest["coq_version"]
    if installed_coq != manifest_coq:
        print(
            f"ERROR: Coq version mismatch — installed {installed_coq}, "
            f"index expects {manifest_coq}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"Coq version OK: {installed_coq}")

    # ── Library versions ─────────────────────────────────────────────────────
    opam_packages = {
        "mathcomp": "rocq-mathcomp-ssreflect",
        "stdpp": "coq-stdpp",
        "flocq": "coq-flocq",
        "coquelicot": "coq-coquelicot",
        "coqinterval": "coq-interval",
    }

    libs = manifest.get("libraries", {})
    for lib_id, entry in libs.items():
        expected_ver = entry["version"]
        if lib_id == "stdlib":
            installed_ver = installed_coq
        else:
            pkg = opam_packages.get(lib_id)
            if not pkg:
                print(
                    f"WARNING: unknown library {lib_id}, skipping version check",
                    file=sys.stderr,
                )
                continue
            r = subprocess.run(
                ["opam", "show", pkg, "--field=version"],
                capture_output=True,
                text=True,
            )
            installed_ver = r.stdout.strip().strip('"')
        if installed_ver != expected_ver:
            print(
                f"ERROR: {lib_id} version mismatch — installed {installed_ver}, "
                f"index expects {expected_ver}",
                file=sys.stderr,
            )
            sys.exit(1)
        print(f"{lib_id} version OK: {installed_ver}")

    print("All versions validated.")
    # Cleanup temp files
    for f in ["/tmp/manifest.json"]:
        if os.path.exists(f):
            os.remove(f)


if __name__ == "__main__":
    main()
