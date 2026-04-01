#!/usr/bin/env bash
set -euo pipefail

DB="/data/index.db"
CHECKPOINT="/data/model.pt"
OUTPUT="/data/evaluation-results.json"
DATA_GLOB="/data/training-*.jsonl"

usage() {
    echo "Usage: $(basename "$0") [--checkpoint PATH] [--db PATH] [--output PATH]" >&2
    echo "" >&2
    echo "Evaluate a trained model: retrieval metrics then neural vs. symbolic comparison." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --checkpoint   Model checkpoint path (default: $CHECKPOINT)" >&2
    echo "  --db           Index database path (default: $DB)" >&2
    echo "  --output       JSON output path (default: $OUTPUT)" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --checkpoint) CHECKPOINT="$2"; shift 2 ;;
        --db) DB="$2"; shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
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
EVAL_JSON=$(poule evaluate --json --checkpoint "$CHECKPOINT" --test-data "$TEST_DATA" --db "$DB")
echo "$EVAL_JSON" | python -m json.tool 2>/dev/null || echo "$EVAL_JSON"

echo ""
echo "=== Step 2: Compare neural vs. symbolic vs. union ==="
COMPARE_JSON=$(poule compare --json --checkpoint "$CHECKPOINT" --test-data "$TEST_DATA" --db "$DB")
echo "$COMPARE_JSON" | python -m json.tool 2>/dev/null || echo "$COMPARE_JSON"

# Write combined results
python -c "
import json, sys
results = {
    'evaluate': json.loads(sys.argv[1]),
    'compare': json.loads(sys.argv[2]),
}
with open(sys.argv[3], 'w') as f:
    json.dump(results, f, indent=2)
print(f'\nResults written to {sys.argv[3]}')
" "$EVAL_JSON" "$COMPARE_JSON" "$OUTPUT"
