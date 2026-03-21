#!/usr/bin/env bash
set -euo pipefail

ALL_LIBRARIES="stdlib,mathcomp,stdpp,flocq,coquelicot,coqinterval"
LIBRARIES="$ALL_LIBRARIES"
OUTPUT_DIR="/data"
FORCE=false

usage() {
    echo "Usage: $(basename "$0") [--libraries lib1,lib2,...] [--force]" >&2
    echo "" >&2
    echo "Build per-library Coq index databases." >&2
    echo "Only rebuilds indexes whose installed library version differs" >&2
    echo "from the version recorded in the existing index-*.db file." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --libraries   Comma-separated list of libraries (default: all 6)" >&2
    echo "  --force       Rebuild all indexes regardless of version" >&2
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

IFS=',' read -ra LIB_ARRAY <<< "$LIBRARIES"

# --- Seed from GitHub Releases if no index files exist ---
# On a fresh container there are no index-*.db files.  Download them
# from the published releases so that only libraries whose versions have
# actually changed need to be rebuilt from scratch.

has_indexes=false
for lib in "${LIB_ARRAY[@]}"; do
    if [[ -f "${OUTPUT_DIR}/index-${lib}.db" ]]; then
        has_indexes=true
        break
    fi
done

if [[ "$has_indexes" == false ]]; then
    echo "No existing index files found. Downloading from GitHub Releases..." >&2

    TAG_LIBRARIES="index-libraries"
    TAG_MERGED="index-merged"

    if gh release view "$TAG_LIBRARIES" &>/dev/null; then
        for lib in "${LIB_ARRAY[@]}"; do
            asset="index-${lib}.db"
            echo "  Downloading ${asset}..." >&2
            if ! gh release download "$TAG_LIBRARIES" -p "$asset" -D "$OUTPUT_DIR" --clobber 2>/dev/null; then
                echo "  Warning: failed to download ${asset}, will build from scratch." >&2
            fi
        done
    else
        echo "  No ${TAG_LIBRARIES} release found. Will build all from scratch." >&2
    fi

    if gh release view "$TAG_MERGED" &>/dev/null; then
        echo "  Downloading index.db..." >&2
        if ! gh release download "$TAG_MERGED" -p "index.db" -D "$OUTPUT_DIR" --clobber 2>/dev/null; then
            echo "  Warning: failed to download index.db, will regenerate after build." >&2
        fi
    else
        echo "  No ${TAG_MERGED} release found. Will generate after build." >&2
    fi

    echo "" >&2
fi

# --- Map library identifiers to opam package names ---

declare -A OPAM_PACKAGES=(
    [mathcomp]=rocq-mathcomp-ssreflect
    [stdpp]=coq-stdpp
    [flocq]=coq-flocq
    [coquelicot]=coq-coquelicot
    [coqinterval]=coq-interval
)

# --- Detect installed versions ---

installed_version() {
    local lib="$1"
    if [[ "$lib" == "stdlib" ]]; then
        coqc --version 2>/dev/null | grep -oP 'version\s+\K[\d.]+'
    else
        local pkg="${OPAM_PACKAGES[$lib]}"
        opam show "$pkg" --field=version 2>/dev/null | tr -d '"'
    fi
}

# --- Read indexed version from an existing index-*.db ---

indexed_version() {
    local db_path="$1"
    if [[ -f "$db_path" ]]; then
        sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key = 'library_version'" 2>/dev/null || true
    fi
}

# --- Display installed versions ---

echo "Installed library versions:"
declare -A INSTALLED
for lib in "${LIB_ARRAY[@]}"; do
    ver=$(installed_version "$lib")
    INSTALLED[$lib]="${ver:-unknown}"
    printf "  %-15s %s\n" "$lib" "${INSTALLED[$lib]}"
done
echo ""

# --- Compare and rebuild ---

declare -A RESULTS
declare -A COUNTS
FAILED=0
REBUILT=0

for lib in "${LIB_ARRAY[@]}"; do
    db_path="${OUTPUT_DIR}/index-${lib}.db"
    idx_ver=$(indexed_version "$db_path")

    if [[ "$FORCE" != true && -n "$idx_ver" && "$idx_ver" == "${INSTALLED[$lib]}" ]]; then
        count=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key = 'declarations'" 2>/dev/null || echo "?")
        RESULTS[$lib]="up-to-date"
        COUNTS[$lib]="$count"
        continue
    fi

    if [[ -n "$idx_ver" && "$idx_ver" != "${INSTALLED[$lib]}" ]]; then
        echo "Version changed for ${lib}: ${idx_ver} -> ${INSTALLED[$lib]}" >&2
    elif [[ -z "$idx_ver" ]]; then
        echo "No existing index for ${lib}" >&2
    fi

    echo "Building index for ${lib}..." >&2
    if python -m Poule.extraction --target "$lib" --db "$db_path" --progress; then
        count=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key = 'declarations'" 2>/dev/null || echo "?")
        RESULTS[$lib]="rebuilt"
        COUNTS[$lib]="$count"
        REBUILT=$((REBUILT + 1))
    else
        RESULTS[$lib]="FAILED"
        COUNTS[$lib]="-"
        FAILED=1
    fi
done

echo ""
echo "Library          Version    Status       Declarations"
echo "---------------  ---------  -----------  ------------"
for lib in "${LIB_ARRAY[@]}"; do
    printf "%-15s  %-9s  %-11s  %s\n" "$lib" "${INSTALLED[$lib]}" "${RESULTS[$lib]}" "${COUNTS[$lib]}"
done

if [[ "$REBUILT" -eq 0 ]]; then
    echo ""
    echo "All indexes are up to date."
fi

if [[ "$FAILED" -eq 1 ]]; then
    echo "" >&2
    echo "Some libraries failed to build." >&2
    exit 1
fi

# --- Merge per-library indexes into index.db (if needed) ---

INDEX_DB="${OUTPUT_DIR}/index.db"
LIB_LIST="${LIB_ARRAY[*]}"
NEED_MERGE=false

# If any library was rebuilt, always re-merge (content may differ even
# at the same version, e.g. after extraction pipeline improvements).
if [[ "$REBUILT" -gt 0 ]]; then
    NEED_MERGE=true
    echo "Re-merging: ${REBUILT} library index(es) were rebuilt." >&2
elif [[ ! -f "$INDEX_DB" ]]; then
    NEED_MERGE=true
else
    # Compare library_versions in index.db against per-library index versions
    merged_versions=$(sqlite3 "$INDEX_DB" "SELECT value FROM index_meta WHERE key = 'library_versions'" 2>/dev/null || true)
    if [[ -z "$merged_versions" ]]; then
        NEED_MERGE=true
    else
        for lib in "${LIB_ARRAY[@]}"; do
            per_lib_ver=$(indexed_version "${OUTPUT_DIR}/index-${lib}.db")
            merged_lib_ver=$(python -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get(sys.argv[2],''))" "$merged_versions" "$lib")
            if [[ "$per_lib_ver" != "$merged_lib_ver" ]]; then
                echo "index.db out of date: ${lib} ${merged_lib_ver} -> ${per_lib_ver}" >&2
                NEED_MERGE=true
            fi
        done
    fi
fi

if [[ "$NEED_MERGE" == true ]]; then
    echo ""
    echo "Merging into ${INDEX_DB}..."
    python -c "
from pathlib import Path
from Poule.storage.merge import merge_indexes

sources = []
for lib in '${LIB_LIST}'.split():
    sources.append((lib, Path('${OUTPUT_DIR}') / f'index-{lib}.db'))

result = merge_indexes(sources, Path('${INDEX_DB}'))

print(f'  Declarations: {result[\"total_declarations\"]}')
print(f'  Dependencies: {result[\"total_dependencies\"]}')
print(f'  Dropped deps: {result[\"dropped_dependencies\"]}')
print(f'  Libraries:    {\", \".join(result[\"libraries\"])}')
"
else
    echo ""
    echo "index.db is up to date."
fi

# --- Restart the MCP server if it's running ---

if command -v poule-mcp &>/dev/null && poule-mcp status 2>/dev/null | grep -q running; then
    echo ""
    echo "Restarting MCP server..."
    poule-mcp restart
fi
