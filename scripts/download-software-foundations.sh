#!/usr/bin/env bash
set -euo pipefail

# Download and unpack all Software Foundations volumes from
# https://softwarefoundations.cis.upenn.edu into software-foundations/.
#
# Run from the project root:
#   ./scripts/download-software-foundations.sh
#
# Each volume is downloaded as a tarball, unpacked, and the HTML files
# are placed under software-foundations/{vol}/.  The tarballs are
# deleted after extraction.

BASE_URL="https://softwarefoundations.cis.upenn.edu"
OUTPUT_DIR="software-foundations"
VOLUMES=(lf plf vfa qc secf slf vc)
VOLUME_NAMES=(
    "Logical Foundations"
    "Programming Language Foundations"
    "Verified Functional Algorithms"
    "QuickChick"
    "Security Foundations"
    "Separation Logic Foundations"
    "Verifiable C"
)
FORCE=false

usage() {
    echo "Usage: $(basename "$0") [--force]" >&2
    echo "" >&2
    echo "Download all Software Foundations volumes." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --force   Re-download even if the volume directory already exists" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

mkdir -p "$OUTPUT_DIR"

echo "==> Downloading Software Foundations volumes to $OUTPUT_DIR/"
echo ""

downloaded=0
skipped=0

for i in "${!VOLUMES[@]}"; do
    vol="${VOLUMES[$i]}"
    name="${VOLUME_NAMES[$i]}"
    vol_dir="$OUTPUT_DIR/$vol"
    tarball_url="$BASE_URL/${vol}-current/${vol}.tgz"

    if [[ -d "$vol_dir" ]] && [[ "$FORCE" != "true" ]]; then
        echo "  [$vol] ${name} — already exists, skipping (use --force to re-download)"
        skipped=$((skipped + 1))
        continue
    fi

    echo "  [$vol] ${name} — downloading..."
    rm -rf "$vol_dir"
    mkdir -p "$vol_dir"

    # Download and extract in one step.
    # The tarball contains a top-level directory (e.g., lf/) so we strip it.
    if ! curl -fsSL "$tarball_url" | tar xz -C "$vol_dir" --strip-components=1; then
        echo "  [$vol] ERROR: download failed from $tarball_url" >&2
        rm -rf "$vol_dir"
        continue
    fi

    file_count=$(find "$vol_dir" -name "*.html" | wc -l)
    echo "  [$vol] ${name} — ${file_count} HTML files"
    downloaded=$((downloaded + 1))
done

echo ""
echo "Done: $downloaded downloaded, $skipped skipped"
echo "Total size: $(du -sh "$OUTPUT_DIR" | cut -f1)"
