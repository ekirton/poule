#!/usr/bin/env bash
set -euo pipefail

DB="/data/index.db"
CHECKPOINT="/data/model.pt"
DATA_GLOB="/data/training-*.jsonl"

usage() {
    echo "Usage: $(basename "$0") [--checkpoint PATH] [--db PATH]" >&2
    echo "" >&2
    echo "Evaluate a trained model: retrieval metrics then neural vs. symbolic comparison." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --checkpoint   Model checkpoint path (default: $CHECKPOINT)" >&2
    echo "  --db           Index database path (default: $DB)" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --checkpoint) CHECKPOINT="$2"; shift 2 ;;
        --db) DB="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# Find the first training data file for evaluation
DATA_FILES=( $DATA_GLOB )
if [[ ${#DATA_FILES[@]} -eq 0 ]]; then
    echo "Error: no training data files matching $DATA_GLOB" >&2
    exit 1
fi
TEST_DATA="${DATA_FILES[0]}"

if [[ ! -f "$CHECKPOINT" ]]; then
    ALT="${CHECKPOINT%.pt}.safetensors"
    if [[ "$CHECKPOINT" == *.pt ]] && [[ -f "$ALT" ]]; then
        CHECKPOINT="$ALT"
        echo "Using $CHECKPOINT (no .pt found)"
    else
        echo "Error: checkpoint not found at $CHECKPOINT" >&2
        exit 1
    fi
fi

echo "=== Step 1: Retrieval metrics (R@1, R@10, R@32, MRR) ==="
poule evaluate --checkpoint "$CHECKPOINT" --test-data "$TEST_DATA" --db "$DB"

echo ""
echo "=== Step 2: Compare neural vs. symbolic vs. union ==="
poule compare --checkpoint "$CHECKPOINT" --test-data "$TEST_DATA" --db "$DB"
