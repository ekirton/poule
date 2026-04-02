#!/usr/bin/env bash
set -euo pipefail

# Collapse per-library training JSONL files into a single file with
# normalized tactic families.  Merges rare and malformed tactic families
# into their parent tactic or "other".  Original files are unchanged.
#
# Usage:
#   ./scripts/collapse-training-data.sh
#   ./scripts/collapse-training-data.sh --min-count 100
#   ./scripts/collapse-training-data.sh --dry-run
#   ./scripts/collapse-training-data.sh --input-dir /data --output /data/training.jsonl

INPUT_DIR="/data"
OUTPUT="/data/training.jsonl"
MIN_COUNT=50
DRY_RUN=false
JSON_MODE=false

usage() {
    echo "Usage: $(basename "$0") [OPTIONS]" >&2
    echo "" >&2
    echo "Collapse per-library training JSONL into a single file with" >&2
    echo "normalized tactic families.  Original files are not modified." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --input-dir DIR    Directory containing training-*.jsonl (default: /data)" >&2
    echo "  --output PATH      Output file path (default: /data/training.jsonl)" >&2
    echo "  --min-count N      Minimum family count to keep own class (default: 50)" >&2
    echo "  --dry-run          Print distribution without writing output" >&2
    echo "  --json             Output report as JSON" >&2
    echo "  -h, --help         Show this help" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --input-dir)
            INPUT_DIR="$2"
            shift 2
            ;;
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        --min-count)
            MIN_COUNT="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --json)
            JSON_MODE=true
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

# Collect input files
INPUT_FILES=()
for f in "${INPUT_DIR}"/training-*.jsonl; do
    if [[ -f "$f" ]]; then
        INPUT_FILES+=("$f")
    fi
done

if [[ ${#INPUT_FILES[@]} -eq 0 ]]; then
    echo "No training-*.jsonl files found in ${INPUT_DIR}" >&2
    exit 1
fi

echo "Found ${#INPUT_FILES[@]} input file(s) in ${INPUT_DIR}" >&2

# Build command
CMD=(poule collapse-training-data --output "$OUTPUT" --min-count "$MIN_COUNT")

if [[ "$DRY_RUN" == true ]]; then
    CMD+=(--dry-run)
fi

if [[ "$JSON_MODE" == true ]]; then
    CMD+=(--json)
fi

CMD+=("${INPUT_FILES[@]}")

exec "${CMD[@]}"
