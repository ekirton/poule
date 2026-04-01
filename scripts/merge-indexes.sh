#!/usr/bin/env bash
#
# Merge per-library index databases into a single index.db + FAISS sidecar.
# Does not publish anything — see publish-indexes.sh for that.
#
# Usage:
#   ./scripts/merge-indexes.sh [--input-dir DIR]
#
# Prerequisites: sqlite3, python (with Poule installed)
# Run ./scripts/build-indexes.sh first to build the per-library indexes.

set -euo pipefail

LIBRARIES="stdlib mathcomp stdpp flocq coquelicot coqinterval"
INPUT_DIR="/data"

usage() {
    echo "Usage: $0 [--input-dir DIR]"
    echo
    echo "Merge per-library index-*.db files into a single index.db + FAISS sidecar."
    echo
    echo "Options:"
    echo "  --input-dir DIR   Directory containing index-*.db files (default: /data)"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input-dir)
            if [[ $# -lt 2 ]]; then
                echo "Error: --input-dir requires a path argument." >&2
                usage
            fi
            INPUT_DIR="$2"
            shift 2
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

# --- Validate prerequisites ---

for cmd in sqlite3 python; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: ${cmd} not found." >&2
        exit 1
    fi
done

# --- Validate files exist ---

DB_PATHS=()
for lib in $LIBRARIES; do
    db="${INPUT_DIR}/index-${lib}.db"
    if [[ ! -f "$db" ]]; then
        echo "Error: ${db} does not exist." >&2
        exit 1
    fi
    DB_PATHS+=("$db")
done

INDEX_DB="${INPUT_DIR}/index.db"

# --- Merge per-library indexes into index.db (if needed) ---

NEED_MERGE=false
LIB_LIST="$LIBRARIES"

if [[ ! -f "$INDEX_DB" ]]; then
    NEED_MERGE=true
else
    # Compare library_versions in index.db against per-library index versions
    merged_versions=$(sqlite3 "$INDEX_DB" "SELECT value FROM index_meta WHERE key = 'library_versions'" 2>/dev/null || true)
    if [[ -z "$merged_versions" ]]; then
        NEED_MERGE=true
    else
        for lib in $LIBRARIES; do
            per_lib_ver=""
            per_lib_db="${INPUT_DIR}/index-${lib}.db"
            if [[ -f "$per_lib_db" ]]; then
                per_lib_ver=$(sqlite3 "$per_lib_db" "SELECT value FROM index_meta WHERE key = 'library_version'" 2>/dev/null || true)
            fi
            merged_lib_ver=$(python -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get(sys.argv[2],''))" "$merged_versions" "$lib")
            if [[ "$per_lib_ver" != "$merged_lib_ver" ]]; then
                echo "index.db out of date: ${lib} ${merged_lib_ver} -> ${per_lib_ver}" >&2
                NEED_MERGE=true
            fi
        done
    fi
fi

if [[ "$NEED_MERGE" == true ]]; then
    echo "Merging per-library indexes into ${INDEX_DB}..."
    python -c "
from pathlib import Path
from Poule.storage.merge import merge_indexes

sources = []
for lib in '${LIB_LIST}'.split():
    sources.append((lib, Path('${INPUT_DIR}') / f'index-{lib}.db'))

result = merge_indexes(sources, Path('${INDEX_DB}'))

print(f'  Declarations: {result[\"total_declarations\"]}')
print(f'  Dependencies: {result[\"total_dependencies\"]}')
print(f'  Dropped deps: {result[\"dropped_dependencies\"]}')
print(f'  Libraries:    {\", \".join(result[\"libraries\"])}')
"
    echo
else
    echo "index.db is up to date."
fi

echo
echo "Done. Output:"
echo "  ${INDEX_DB}"
