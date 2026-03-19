#!/usr/bin/env bash
#
# Merge per-library index databases into index.db and publish as a GitHub Release.
#
# Usage:
#   ./scripts/merge-and-publish.sh [--input-dir DIR] [--model MODEL_PATH] [--replace]
#
# Prerequisites: python (with Poule package), gh (authenticated), sqlite3, shasum

set -euo pipefail

LIBRARIES="stdlib mathcomp stdpp flocq coquelicot coqinterval"
INPUT_DIR="/data"
MODEL_PATH=""
REPLACE=false

usage() {
    echo "Usage: $0 [--input-dir DIR] [--model MODEL_PATH] [--replace]"
    echo
    echo "Merge per-library index-*.db files into index.db and publish as a GitHub Release."
    echo
    echo "Options:"
    echo "  --input-dir DIR      Directory containing index-*.db files (default: /data)"
    echo "  --model MODEL_PATH   Also upload an ONNX model file"
    echo "  --replace            Replace existing release if tag already exists"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input-dir)
            INPUT_DIR="$2"
            shift 2
            ;;
        --model)
            if [[ $# -lt 2 ]]; then
                echo "Error: --model requires a path argument." >&2
                usage
            fi
            MODEL_PATH="$2"
            shift 2
            ;;
        --replace)
            REPLACE=true
            shift
            ;;
        --help|-h)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

# --- Validate per-library DBs exist ---

DB_PATHS=()
for lib in $LIBRARIES; do
    db="${INPUT_DIR}/index-${lib}.db"
    if [[ ! -f "$db" ]]; then
        echo "Error: ${db} does not exist." >&2
        exit 1
    fi
    DB_PATHS+=("$db")
done

echo "Per-library indexes:"
for db in "${DB_PATHS[@]}"; do
    printf "  %s\n" "$db"
done

# --- Merge into index.db ---

INDEX_DB="${INPUT_DIR}/index.db"
echo
echo "Merging into ${INDEX_DB}..."

python -c "
from pathlib import Path
from Poule.storage.merge import merge_indexes

sources = []
for lib in '${LIBRARIES}'.split():
    sources.append((lib, Path('${INPUT_DIR}') / f'index-{lib}.db'))

result = merge_indexes(sources, Path('${INDEX_DB}'))

print(f\"  Declarations: {result['total_declarations']}\")
print(f\"  Dependencies: {result['total_dependencies']}\")
print(f\"  Dropped deps: {result['dropped_dependencies']}\")
print(f\"  Libraries:    {', '.join(result['libraries'])}\")
"

echo

# --- Publish ---

publish_args=()
if [[ "$REPLACE" == true ]]; then
    publish_args+=(--replace)
fi
if [[ -n "$MODEL_PATH" ]]; then
    publish_args+=(--model "$MODEL_PATH")
fi

exec ./scripts/publish-release.sh "${DB_PATHS[@]}" "${publish_args[@]}"
