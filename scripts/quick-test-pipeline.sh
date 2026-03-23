#!/usr/bin/env bash
set -euo pipefail

# Quick-test the indexing and extraction pipelines.
#
# Usage:
#   ./scripts/quick-test-pipeline.sh                        # smoke tier (4 files)
#   ./scripts/quick-test-pipeline.sh --tier debug            # debug tier (14 files)
#   ./scripts/quick-test-pipeline.sh --library coquelicot    # full library
#   ./scripts/quick-test-pipeline.sh --index-only            # index only
#   ./scripts/quick-test-pipeline.sh --extract-only          # extract only (needs prior index)

export ROCQLIB="${ROCQLIB:-${COQLIB:-}}"

TIER=""
LIBRARY=""
OUTPUT_DIR="/data/quick-test"
INDEX_ONLY=false
EXTRACT_ONLY=false
WATCHDOG_TIMEOUT=120

VALID_LIBRARIES="stdlib, mathcomp, stdpp, flocq, coquelicot, coqinterval"

usage() {
    echo "Usage: $(basename "$0") [--tier smoke|debug] [--library NAME] [--output-dir DIR]" >&2
    echo "                        [--index-only] [--extract-only]" >&2
    echo "" >&2
    echo "Run indexing and extraction for fast pipeline testing." >&2
    echo "" >&2
    echo "Tiers (stdlib subsets, default: smoke):" >&2
    echo "  smoke   Stdlib/Bool   (4 .vo files,  ~30 seconds)" >&2
    echo "  debug   Stdlib/Arith  (14 .vo files, ~1-2 minutes)" >&2
    echo "" >&2
    echo "Libraries:" >&2
    echo "  ${VALID_LIBRARIES}" >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --tier          Test tier (default: smoke). Mutually exclusive with --library." >&2
    echo "  --library       Run on an entire installed library." >&2
    echo "  --output-dir    Output directory (default: /data/quick-test)" >&2
    echo "  --index-only    Run only the indexing phase" >&2
    echo "  --extract-only  Run only the extraction phase (requires prior index)" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --tier)
            TIER="$2"
            shift 2
            ;;
        --library)
            LIBRARY="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --index-only)
            INDEX_ONLY=true
            shift
            ;;
        --extract-only)
            EXTRACT_ONLY=true
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

if [[ -n "$LIBRARY" && -n "$TIER" ]]; then
    echo "ERROR: --library and --tier are mutually exclusive" >&2
    exit 1
fi

# Default to smoke tier when neither is specified
if [[ -z "$LIBRARY" && -z "$TIER" ]]; then
    TIER="smoke"
fi

# --- Resolve Coq library path ---

COQ_LIB="$(coqc -where 2>/dev/null)"

# --- Library contrib directory and module prefix mappings ---
# (mirrors _LIBRARY_CONTRIB_DIRS and module conventions in pipeline.py)

declare -A LIB_CONTRIB_DIRS=(
    [mathcomp]=mathcomp
    [stdpp]=stdpp
    [flocq]=Flocq
    [coquelicot]=Coquelicot
    [coqinterval]=Interval
)

declare -A LIB_MODULE_PREFIXES=(
    [stdlib]="Coq."
    [mathcomp]="mathcomp."
    [stdpp]="stdpp."
    [flocq]="Flocq."
    [coquelicot]="Coquelicot."
    [coqinterval]="Interval."
)

# --- Resolve stdlib root (used by both tier and --library stdlib) ---

resolve_stdlib_root() {
    local root="${COQ_LIB}/user-contrib/Stdlib"
    if [[ ! -d "$root" ]]; then
        root="${COQ_LIB}/theories"
    fi
    echo "$root"
}

# --- Determine target configuration ---

if [[ -n "$LIBRARY" ]]; then
    # --library mode: index and extract a full library
    if [[ -z "${LIB_MODULE_PREFIXES[$LIBRARY]+x}" ]]; then
        echo "Unknown library: $LIBRARY" >&2
        echo "Valid libraries: ${VALID_LIBRARIES}" >&2
        exit 1
    fi

    MODULE_PREFIX="${LIB_MODULE_PREFIXES[$LIBRARY]}"
    MODULE_FILTER=""

    if [[ "$LIBRARY" == "stdlib" ]]; then
        PROJECT_DIR="$(resolve_stdlib_root)"
    else
        CONTRIB_NAME="${LIB_CONTRIB_DIRS[$LIBRARY]}"
        PROJECT_DIR="${COQ_LIB}/user-contrib/${CONTRIB_NAME}"
    fi

    if [[ ! -d "$PROJECT_DIR" ]]; then
        echo "ERROR: Library not found: ${PROJECT_DIR}" >&2
        echo "Is ${LIBRARY} installed?" >&2
        exit 1
    fi

    # Use library name as indexing target (pipeline.py resolves it)
    INDEX_TARGET="$LIBRARY"
    LABEL="library: ${LIBRARY}"
    DB_SUFFIX="$LIBRARY"
else
    # --tier mode: stdlib subset
    STDLIB_ROOT="$(resolve_stdlib_root)"

    case "$TIER" in
        smoke)
            INDEX_TARGET="${STDLIB_ROOT}/Bool"
            MODULE_FILTER="Coq.Bool."
            ;;
        debug)
            INDEX_TARGET="${STDLIB_ROOT}/Arith"
            MODULE_FILTER="Coq.Arith."
            ;;
        *)
            echo "Unknown tier: $TIER (expected smoke or debug)" >&2
            exit 1
            ;;
    esac

    PROJECT_DIR="$STDLIB_ROOT"
    MODULE_PREFIX="Coq."
    LABEL="tier: ${TIER}"
    DB_SUFFIX="quick"
fi

if [[ -z "$LIBRARY" && ! -d "$INDEX_TARGET" ]]; then
    echo "ERROR: Index target not found: ${INDEX_TARGET}" >&2
    exit 1
fi

VO_COUNT=$(find "$PROJECT_DIR" -name "*.vo" | wc -l)

mkdir -p "$OUTPUT_DIR"

DB_PATH="${OUTPUT_DIR}/index-${DB_SUFFIX}.db"
JSONL_PATH="${OUTPUT_DIR}/${DB_SUFFIX}.jsonl"

echo "Quick test pipeline — ${LABEL}"
echo "  Index target:   ${INDEX_TARGET} (${VO_COUNT} .vo files)"
echo "  Module prefix:  ${MODULE_PREFIX}"
if [[ -n "$MODULE_FILTER" ]]; then
    echo "  Module filter:  ${MODULE_FILTER}"
fi
echo "  Output dir:     ${OUTPUT_DIR}"
echo ""

OVERALL_START=$(date +%s)

# --- Indexing phase ---

if [[ "$EXTRACT_ONLY" != true ]]; then
    echo "=== Indexing ===" >&2
    rm -f "$DB_PATH"
    INDEX_START=$(date +%s)

    python -m Poule.extraction --target "$INDEX_TARGET" --db "$DB_PATH" --progress

    INDEX_END=$(date +%s)
    INDEX_ELAPSED=$((INDEX_END - INDEX_START))

    DECL_COUNT=$(sqlite3 "$DB_PATH" "SELECT value FROM index_meta WHERE key = 'declarations'" 2>/dev/null || echo "?")
    echo ""
    echo "  Indexed ${DECL_COUNT} declarations in ${INDEX_ELAPSED}s"
    echo ""
fi

# --- Extraction phase ---

if [[ "$INDEX_ONLY" != true ]]; then
    if [[ ! -f "$DB_PATH" ]]; then
        echo "ERROR: Index database not found at ${DB_PATH}" >&2
        echo "Run without --extract-only first, or use --index-only to build it." >&2
        exit 1
    fi

    echo "=== Extraction ===" >&2
    rm -f "$JSONL_PATH"
    EXTRACT_START=$(date +%s)

    EXTRACT_ARGS=(
        "$PROJECT_DIR"
        --output "$JSONL_PATH"
        --index-db "$DB_PATH"
        --module-prefix "$MODULE_PREFIX"
        --watchdog-timeout "$WATCHDOG_TIMEOUT"
    )
    if [[ -n "$MODULE_FILTER" ]]; then
        EXTRACT_ARGS+=(--modules "$MODULE_FILTER")
    fi

    poule extract "${EXTRACT_ARGS[@]}"

    EXTRACT_END=$(date +%s)
    EXTRACT_ELAPSED=$((EXTRACT_END - EXTRACT_START))

    echo ""
    echo "  Extraction completed in ${EXTRACT_ELAPSED}s"
    echo ""
fi

# --- Summary ---

OVERALL_END=$(date +%s)
OVERALL_ELAPSED=$((OVERALL_END - OVERALL_START))

echo "=== Summary ==="
echo "  ${LABEL^}"
echo "  Total time: ${OVERALL_ELAPSED}s"

if [[ -f "$DB_PATH" ]]; then
    DB_SIZE=$(du -h "$DB_PATH" | cut -f1)
    DECL_COUNT=$(sqlite3 "$DB_PATH" "SELECT value FROM index_meta WHERE key = 'declarations'" 2>/dev/null || echo "?")
    echo "  Index:      ${DB_PATH} (${DB_SIZE}, ${DECL_COUNT} declarations)"
fi

if [[ -f "$JSONL_PATH" ]]; then
    JSONL_SIZE=$(du -h "$JSONL_PATH" | cut -f1)
    PROOF_COUNTS=$(tail -1 "$JSONL_PATH" 2>/dev/null | python3 -c "
import json, sys
try:
    s = json.loads(sys.stdin.readline())
    if s.get('record_type') == 'extraction_summary':
        print(f\"{s['total_extracted']} extracted, {s['total_failed']} failed\")
except Exception:
    pass
" 2>/dev/null || true)
    echo "  Output:     ${JSONL_PATH} (${JSONL_SIZE}${PROOF_COUNTS:+, ${PROOF_COUNTS}})"
fi
