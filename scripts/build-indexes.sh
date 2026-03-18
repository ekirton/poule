#!/usr/bin/env bash
set -euo pipefail

ALL_LIBRARIES="stdlib,mathcomp,stdpp,flocq,coquelicot,coqinterval"
LIBRARIES="$ALL_LIBRARIES"
OUTPUT_DIR="."

usage() {
    echo "Usage: $(basename "$0") [--libraries lib1,lib2,...] [--output-dir DIR]" >&2
    echo "" >&2
    echo "Build per-library Coq index databases." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --libraries   Comma-separated list of libraries (default: all 6)" >&2
    echo "  --output-dir  Directory for output databases (default: .)" >&2
    echo "" >&2
    echo "Libraries: stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --libraries)
            LIBRARIES="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
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

IFS=',' read -ra LIB_ARRAY <<< "$LIBRARIES"

declare -A RESULTS
declare -A COUNTS
FAILED=0

for lib in "${LIB_ARRAY[@]}"; do
    db_path="${OUTPUT_DIR}/index-${lib}.db"
    echo "Building index for ${lib}..." >&2
    if python -m Poule.extraction --target "$lib" --db "$db_path" --progress; then
        count=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key = 'declarations';" 2>/dev/null || echo "?")
        RESULTS[$lib]="ok"
        COUNTS[$lib]="$count"
    else
        RESULTS[$lib]="FAILED"
        COUNTS[$lib]="-"
        FAILED=1
    fi
done

echo ""
echo "Library          Status   Declarations"
echo "---------------  -------  ------------"
for lib in "${LIB_ARRAY[@]}"; do
    printf "%-15s  %-7s  %s\n" "$lib" "${RESULTS[$lib]}" "${COUNTS[$lib]}"
done

if [[ "$FAILED" -eq 1 ]]; then
    echo "" >&2
    echo "Some libraries failed to build." >&2
    exit 1
fi
