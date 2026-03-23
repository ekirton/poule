#!/usr/bin/env bash
set -euo pipefail

# Quick-test the indexing and extraction pipelines on a small stdlib subset.
#
# Usage:
#   ./scripts/quick-test-pipeline.sh                     # smoke tier (4 files)
#   ./scripts/quick-test-pipeline.sh --tier debug         # debug tier (14 files)
#   ./scripts/quick-test-pipeline.sh --index-only         # index only
#   ./scripts/quick-test-pipeline.sh --extract-only       # extract only (needs prior index)

export ROCQLIB="${ROCQLIB:-${COQLIB:-}}"

TIER="smoke"
OUTPUT_DIR="/data/quick-test"
INDEX_ONLY=false
EXTRACT_ONLY=false
WATCHDOG_TIMEOUT=120

usage() {
    echo "Usage: $(basename "$0") [--tier smoke|debug] [--output-dir DIR]" >&2
    echo "                        [--index-only] [--extract-only]" >&2
    echo "" >&2
    echo "Run indexing and extraction on a small stdlib subset for fast testing." >&2
    echo "" >&2
    echo "Tiers:" >&2
    echo "  smoke   Stdlib/Bool   (4 .vo files,  ~30 seconds)" >&2
    echo "  debug   Stdlib/Arith  (14 .vo files, ~1-2 minutes)" >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --tier          Test tier (default: smoke)" >&2
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

# --- Resolve Coq library path ---

COQ_LIB="$(coqc -where 2>/dev/null)"
STDLIB_ROOT="${COQ_LIB}/user-contrib/Stdlib"
if [[ ! -d "$STDLIB_ROOT" ]]; then
    STDLIB_ROOT="${COQ_LIB}/theories"
fi

# --- Map tier to subdirectory and module filter ---

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

if [[ ! -d "$INDEX_TARGET" ]]; then
    echo "ERROR: Index target not found: ${INDEX_TARGET}" >&2
    exit 1
fi

VO_COUNT=$(find "$INDEX_TARGET" -name "*.vo" | wc -l)

mkdir -p "$OUTPUT_DIR"

DB_PATH="${OUTPUT_DIR}/index-quick.db"
JSONL_PATH="${OUTPUT_DIR}/quick.jsonl"

echo "Quick test pipeline — tier: ${TIER}"
echo "  Index target:  ${INDEX_TARGET} (${VO_COUNT} .vo files)"
echo "  Module filter: ${MODULE_FILTER}"
echo "  Output dir:    ${OUTPUT_DIR}"
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

    poule extract "$STDLIB_ROOT" \
        --output "$JSONL_PATH" \
        --index-db "$DB_PATH" \
        --module-prefix "Coq." \
        --modules "$MODULE_FILTER" \
        --watchdog-timeout "$WATCHDOG_TIMEOUT"

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
echo "  Tier:       ${TIER}"
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
