#!/usr/bin/env bash
set -euo pipefail

# Extract proof traces from Coq libraries for neural premise selection
# training.  Calls `poule extract` for each library that has .v source
# files, writing JSONL output to /data/.
#
# Usage:
#   ./scripts/extract-training-data.sh
#   ./scripts/extract-training-data.sh --libraries stdlib,mathcomp
#   ./scripts/extract-training-data.sh --force --watchdog-timeout 300

# Rocq 9.x deprecates COQLIB in favour of ROCQLIB; export it so coqc
# stops emitting the deprecation warning on every invocation.
export ROCQLIB="${ROCQLIB:-${COQLIB:-}}"

ALL_LIBRARIES="stdlib,mathcomp,stdpp,flocq,coquelicot,coqinterval"
LIBRARIES="$ALL_LIBRARIES"
OUTPUT_DIR="/data"
FORCE=false
WATCHDOG_TIMEOUT=60
WORKERS=0

usage() {
    echo "Usage: $(basename "$0") [--libraries lib1,lib2,...] [--force] [--watchdog-timeout N] [--workers N]" >&2
    echo "" >&2
    echo "Extract proof traces from Coq libraries for neural training." >&2
    echo "Only re-extracts libraries whose installed version differs from" >&2
    echo "the version recorded in the existing output file." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --libraries          Comma-separated list of libraries (default: all 6)" >&2
    echo "  --force              Re-extract all libraries regardless of version" >&2
    echo "  --watchdog-timeout N Inactivity threshold in seconds (default: 60, 0 to disable)" >&2
    echo "  --workers N          Parallel workers per library (default: 0 = auto-detect CPU count)" >&2
    echo "  --output-dir         Output directory (default: /data)" >&2
    echo "" >&2
    echo "Libraries: stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval" >&2
    echo "" >&2
    echo "Note: Libraries that do not install .v source files are" >&2
    echo "automatically skipped." >&2
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
        --workers)
            WORKERS="$2"
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

# --- Map library identifiers to source directories ---
# These are the paths under $(coqc -where)/user-contrib/ where .v source
# files are installed alongside .vo files.

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
# These prefixes are stripped from fully-qualified module paths when
# converting to relative source file paths (e.g., Coq.Arith.PeanoNat → Arith/PeanoNat.v).
# They also filter the index to only the relevant library's declarations.

declare -A MODULE_PREFIXES=(
    [stdlib]="Stdlib."
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

# --- Read version from existing JSONL output (first line = campaign_metadata) ---

extracted_version() {
    local jsonl_path="$1"
    if [[ -f "$jsonl_path" ]]; then
        # Extract coq_version from the first project in campaign_metadata
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

# --- Check whether a library has .v source files ---

has_source_files() {
    local lib_path="$1"
    [[ -d "$lib_path" ]] && find "$lib_path" -name "*.v" -print -quit 2>/dev/null | grep -q .
}

# --- Display installed versions and source availability ---

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
        printf "  %-15s %-10s (no .v sources — will skip)\n" "$lib" "${INSTALLED[$lib]}"
    fi
done
echo ""

# --- Extract each library ---

declare -A RESULTS
FAILED=0
EXTRACTED=0
SKIPPED_NO_SRC=0

for lib in "${LIB_ARRAY[@]}"; do
    output_file="${OUTPUT_DIR}/training-${lib}.jsonl"
    lib_path="${LIB_PATHS[$lib]:-}"

    # Skip libraries without .v source files
    if [[ "${HAS_SOURCES[$lib]}" != true ]]; then
        RESULTS[$lib]="skipped (no .v)"
        SKIPPED_NO_SRC=$((SKIPPED_NO_SRC + 1))
        continue
    fi

    # Delete existing output when --force is used
    if [[ "$FORCE" == true && -f "$output_file" ]]; then
        echo "Removing existing ${output_file}" >&2
        rm -f "$output_file"
    fi

    # Check if already extracted at current version
    if [[ "$FORCE" != true && -f "$output_file" ]]; then
        existing_ver=$(extracted_version "$output_file")
        if [[ -n "$existing_ver" && "$existing_ver" == "${INSTALLED[$lib]}" ]]; then
            RESULTS[$lib]="up-to-date"
            continue
        fi
    fi

    INDEX_DB="${OUTPUT_DIR}/index-${lib}.db"
    if [[ ! -f "$INDEX_DB" ]]; then
        # Fall back to merged index
        INDEX_DB="${OUTPUT_DIR}/index.db"
    fi
    if [[ ! -f "$INDEX_DB" ]]; then
        echo "ERROR: Index database not found for ${lib}" >&2
        echo "Build the index first before running extraction." >&2
        RESULTS[$lib]="FAILED (no index)"
        FAILED=1
        continue
    fi
    echo "Using index database at $INDEX_DB" >&2

    echo "Extracting proof traces for ${lib}..." >&2
    module_prefix="${MODULE_PREFIXES[$lib]:-}"
    if poule extract "$lib_path" --output "$output_file" --watchdog-timeout "$WATCHDOG_TIMEOUT" --workers "$WORKERS" --index-db "$INDEX_DB" --module-prefix "$module_prefix"; then
        RESULTS[$lib]="extracted"
        EXTRACTED=$((EXTRACTED + 1))
    else
        RESULTS[$lib]="FAILED"
        FAILED=1
    fi
    echo "" >&2
done

# --- Summary ---

echo ""
echo "Library          Version    Status"
echo "---------------  ---------  -------------------------"
for lib in "${LIB_ARRAY[@]}"; do
    printf "%-15s  %-9s  %s\n" "$lib" "${INSTALLED[$lib]}" "${RESULTS[$lib]}"
done
echo ""

# --- Count total proofs across all output files ---

total_proofs=0
total_failed=0
for lib in "${LIB_ARRAY[@]}"; do
    output_file="${OUTPUT_DIR}/training-${lib}.jsonl"
    if [[ -f "$output_file" ]]; then
        # Read counts from the extraction_summary (last line)
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

if [[ "$SKIPPED_NO_SRC" -gt 0 ]]; then
    echo "Skipped (no .v):    ${SKIPPED_NO_SRC} libraries"
fi

if [[ "$EXTRACTED" -gt 0 ]]; then
    echo ""
    echo "Output files in ${OUTPUT_DIR}/:"
    for lib in "${LIB_ARRAY[@]}"; do
        f="${OUTPUT_DIR}/${lib}.jsonl"
        if [[ -f "$f" ]]; then
            size=$(du -h "$f" | cut -f1)
            echo "  ${lib}.jsonl  ${size}"
        fi
    done
fi

# --- Post-extraction error analysis ---

JSONL_FILES=()
for lib in "${LIB_ARRAY[@]}"; do
    f="${OUTPUT_DIR}/${lib}.jsonl"
    if [[ -f "$f" ]]; then
        JSONL_FILES+=("$f")
    fi
done

if [[ ${#JSONL_FILES[@]} -gt 0 ]]; then
    echo ""
    echo "Running error analysis..."
    poule analyze-errors "${JSONL_FILES[@]}" || true
fi

if [[ "$FAILED" -eq 1 ]]; then
    echo "" >&2
    echo "Some libraries failed to extract." >&2
    exit 1
fi
