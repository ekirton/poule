#!/usr/bin/env bash
set -euo pipefail

# Index Coq libraries and extract proof traces for neural training,
# one library at a time: index stdlib → extract stdlib → index mathcomp → ...
#
# Each library's per-library index (index-${lib}.db) is used directly
# for extraction — no merged index.db is needed.
#
# Usage:
#   ./scripts/index-and-extract-training-data.sh
#   ./scripts/index-and-extract-training-data.sh --libraries stdlib,mathcomp
#   ./scripts/index-and-extract-training-data.sh --force --watchdog-timeout 300

# Rocq 9.x deprecates COQLIB in favour of ROCQLIB; export it so coqc
# stops emitting the deprecation warning on every invocation.
export ROCQLIB="${ROCQLIB:-${COQLIB:-}}"

ALL_LIBRARIES="stdlib,mathcomp,stdpp,flocq,coquelicot,coqinterval"
LIBRARIES="$ALL_LIBRARIES"
OUTPUT_DIR="/data"
FORCE=false
WATCHDOG_TIMEOUT=600

usage() {
    echo "Usage: $(basename "$0") [--libraries lib1,lib2,...] [--force] [--watchdog-timeout N]" >&2
    echo "" >&2
    echo "Index and extract proof traces from Coq libraries, one library at a time." >&2
    echo "Only rebuilds/re-extracts when the installed version differs from" >&2
    echo "the version recorded in the existing output files." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --libraries          Comma-separated list of libraries (default: all 6)" >&2
    echo "  --force              Rebuild indexes and re-extract regardless of version" >&2
    echo "  --watchdog-timeout N Inactivity threshold in seconds (default: 600, 0 to disable)" >&2
    echo "  --output-dir         Output directory (default: /data)" >&2
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
        --watchdog-timeout)
            WATCHDOG_TIMEOUT="$2"
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

    echo "" >&2
fi

# --- Map library identifiers to source directories ---

COQ_LIB="$(coqc -where)"

declare -A LIB_PATHS=(
    [stdlib]="${COQ_LIB}/user-contrib/Stdlib"
    [mathcomp]="${COQ_LIB}/user-contrib/mathcomp"
    [stdpp]="${COQ_LIB}/user-contrib/stdpp"
    [flocq]="${COQ_LIB}/user-contrib/Flocq"
    [coquelicot]="${COQ_LIB}/user-contrib/Coquelicot"
    [coqinterval]="${COQ_LIB}/user-contrib/Interval"
)

# Rocq 9.x may still have stdlib under theories/ instead of user-contrib/
if [[ ! -d "${LIB_PATHS[stdlib]}" ]]; then
    LIB_PATHS[stdlib]="${COQ_LIB}/theories"
fi

# --- Map library identifiers to module prefixes ---

declare -A MODULE_PREFIXES=(
    [stdlib]="Coq."
    [mathcomp]="mathcomp."
    [stdpp]="stdpp."
    [flocq]="Flocq."
    [coquelicot]="Coquelicot."
    [coqinterval]="Interval."
)

# --- Map library identifiers to opam package names ---

declare -A OPAM_PACKAGES=(
    [mathcomp]=rocq-mathcomp-ssreflect
    [stdpp]=coq-stdpp
    [flocq]=coq-flocq
    [coquelicot]=coq-coquelicot
    [coqinterval]=coq-interval
)

# --- Helper functions ---

installed_version() {
    local lib="$1"
    if [[ "$lib" == "stdlib" ]]; then
        coqc --version 2>/dev/null | grep -oP 'version\s+\K[\d.]+'
    else
        local pkg="${OPAM_PACKAGES[$lib]}"
        opam show "$pkg" --field=version 2>/dev/null | tr -d '"'
    fi
}

indexed_version() {
    local db_path="$1"
    if [[ -f "$db_path" ]]; then
        sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key = 'library_version'" 2>/dev/null || true
    fi
}

extracted_version() {
    local jsonl_path="$1"
    if [[ -f "$jsonl_path" ]]; then
        head -1 "$jsonl_path" 2>/dev/null \
            | python3 -c "
import json, sys
try:
    meta = json.loads(sys.stdin.readline())
    if meta.get('record_type') == 'campaign_metadata':
        for p in meta.get('projects', []):
            print(p.get('coq_version', '')); break
except Exception:
    pass
" 2>/dev/null || true
    fi
}

has_source_files() {
    local lib_path="$1"
    [[ -d "$lib_path" ]] && find "$lib_path" -name "*.v" -print -quit 2>/dev/null | grep -q .
}

# --- Display installed versions ---

echo "Installed library versions:"
declare -A INSTALLED
declare -A HAS_SOURCES
for lib in "${LIB_ARRAY[@]}"; do
    ver=$(installed_version "$lib")
    INSTALLED[$lib]="${ver:-unknown}"
    lib_path="${LIB_PATHS[$lib]:-}"
    if [[ -n "$lib_path" ]] && has_source_files "$lib_path"; then
        HAS_SOURCES[$lib]=true
        printf "  %-15s %-10s (.v sources available)\n" "$lib" "${INSTALLED[$lib]}"
    else
        HAS_SOURCES[$lib]=false
        printf "  %-15s %-10s (no .v sources)\n" "$lib" "${INSTALLED[$lib]}"
    fi
done
echo ""

# --- Process each library: index → extract ---

declare -A INDEX_RESULTS
declare -A INDEX_COUNTS
declare -A EXTRACT_RESULTS
FAILED=0

for lib in "${LIB_ARRAY[@]}"; do
    echo "=== ${lib} ===" >&2
    db_path="${OUTPUT_DIR}/index-${lib}.db"
    output_file="${OUTPUT_DIR}/${lib}.jsonl"
    lib_path="${LIB_PATHS[$lib]:-}"

    # --- Index ---

    idx_ver=$(indexed_version "$db_path")

    if [[ "$FORCE" != true && -n "$idx_ver" && "$idx_ver" == "${INSTALLED[$lib]}" ]]; then
        count=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key = 'declarations'" 2>/dev/null || echo "?")
        INDEX_RESULTS[$lib]="up-to-date"
        INDEX_COUNTS[$lib]="$count"
        echo "  Index up to date (${count} declarations)" >&2
    else
        if [[ -n "$idx_ver" && "$idx_ver" != "${INSTALLED[$lib]}" ]]; then
            echo "  Index version changed: ${idx_ver} -> ${INSTALLED[$lib]}" >&2
        elif [[ -z "$idx_ver" ]]; then
            echo "  No existing index" >&2
        fi

        echo "  Building index..." >&2
        if python -m Poule.extraction --target "$lib" --db "$db_path" --progress; then
            count=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key = 'declarations'" 2>/dev/null || echo "?")
            INDEX_RESULTS[$lib]="rebuilt"
            INDEX_COUNTS[$lib]="$count"
            echo "  Index built (${count} declarations)" >&2

            # Index was rebuilt — force re-extraction even without --force
            if [[ -f "$output_file" ]]; then
                echo "  Removing stale ${output_file}" >&2
                rm -f "$output_file"
            fi
        else
            INDEX_RESULTS[$lib]="FAILED"
            INDEX_COUNTS[$lib]="-"
            EXTRACT_RESULTS[$lib]="skipped (index failed)"
            FAILED=1
            echo "" >&2
            continue
        fi
    fi

    # --- Extract ---

    if [[ "${HAS_SOURCES[$lib]}" != true ]]; then
        EXTRACT_RESULTS[$lib]="skipped (no .v)"
        echo "  No .v source files — skipping extraction" >&2
        echo "" >&2
        continue
    fi

    if [[ "$FORCE" == true && -f "$output_file" ]]; then
        echo "  Removing existing ${output_file}" >&2
        rm -f "$output_file"
    fi

    if [[ -f "$output_file" ]]; then
        existing_ver=$(extracted_version "$output_file")
        if [[ -n "$existing_ver" && "$existing_ver" == "${INSTALLED[$lib]}" ]]; then
            EXTRACT_RESULTS[$lib]="up-to-date"
            echo "  Extraction up to date" >&2
            echo "" >&2
            continue
        fi
    fi

    echo "  Extracting proof traces..." >&2
    module_prefix="${MODULE_PREFIXES[$lib]:-}"
    if poule extract "$lib_path" --output "$output_file" --watchdog-timeout "$WATCHDOG_TIMEOUT" --index-db "$db_path" --module-prefix "$module_prefix"; then
        EXTRACT_RESULTS[$lib]="extracted"
    else
        EXTRACT_RESULTS[$lib]="FAILED"
        FAILED=1
    fi
    echo "" >&2
done

# --- Summary ---

echo ""
echo "Library          Version    Index        Decls   Extraction"
echo "---------------  ---------  -----------  ------  -------------------------"
for lib in "${LIB_ARRAY[@]}"; do
    printf "%-15s  %-9s  %-11s  %-6s  %s\n" \
        "$lib" \
        "${INSTALLED[$lib]}" \
        "${INDEX_RESULTS[$lib]:-—}" \
        "${INDEX_COUNTS[$lib]:-—}" \
        "${EXTRACT_RESULTS[$lib]:-—}"
done
echo ""

# --- Count total proofs across all output files ---

total_proofs=0
total_failed=0
for lib in "${LIB_ARRAY[@]}"; do
    output_file="${OUTPUT_DIR}/${lib}.jsonl"
    if [[ -f "$output_file" ]]; then
        counts=$(tail -1 "$output_file" 2>/dev/null | python3 -c "
import json, sys
try:
    s = json.loads(sys.stdin.readline())
    if s.get('record_type') == 'extraction_summary':
        print(f\"{s['total_extracted']} {s['total_failed']}\")
except Exception:
    pass
" 2>/dev/null || true)
        if [[ -n "$counts" ]]; then
            e=$(echo "$counts" | cut -d' ' -f1)
            f=$(echo "$counts" | cut -d' ' -f2)
            total_proofs=$((total_proofs + e))
            total_failed=$((total_failed + f))
        fi
    fi
done

echo "Total proof traces: ${total_proofs}"
echo "Total failed:       ${total_failed}"

JSONL_FILES=()
for lib in "${LIB_ARRAY[@]}"; do
    f="${OUTPUT_DIR}/${lib}.jsonl"
    if [[ -f "$f" ]]; then
        size=$(du -h "$f" | cut -f1)
        echo "  ${lib}.jsonl  ${size}"
        JSONL_FILES+=("$f")
    fi
done

# --- Post-extraction error analysis ---

if [[ ${#JSONL_FILES[@]} -gt 0 ]]; then
    echo ""
    echo "Running error analysis..."
    poule analyze-errors "${JSONL_FILES[@]}" || true
fi

if [[ "$FAILED" -eq 1 ]]; then
    echo "" >&2
    echo "Some libraries failed." >&2
    exit 1
fi
