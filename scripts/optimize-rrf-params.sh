#!/usr/bin/env bash
set -euo pipefail

DB="/data/index.db"
DATA_GLOB="/data/training-*.jsonl"
N_TRIALS_SYM=30
N_TRIALS_COMBINED=50
CHECKPOINT="/data/model.pt"
FORCE=false

usage() {
    echo "Usage: $(basename "$0") [--force] [--checkpoint PATH]" >&2
    echo "" >&2
    echo "Optimize RRF fusion parameters in two phases:" >&2
    echo "  Phase 1: Symbol-only (structural, MePo, FTS)" >&2
    echo "  Phase 2: Combined (symbol + neural)" >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --force        Overwrite existing results" >&2
    echo "  --checkpoint   Neural checkpoint path (default: $CHECKPOINT)" >&2
    echo "  --db           Index database path (default: $DB)" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force) FORCE=true; shift ;;
        --checkpoint) CHECKPOINT="$2"; shift 2 ;;
        --db) DB="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# Collect training data files
DATA_FILES=( $DATA_GLOB )
if [[ ${#DATA_FILES[@]} -eq 0 ]]; then
    echo "Error: no training data files matching $DATA_GLOB" >&2
    exit 1
fi
echo "Training data: ${DATA_FILES[*]}"

is_complete() {
    local dir="$1"
    [[ -d "$dir" ]] && [[ -f "$dir/rrf-study.db" ]]
}

# Phase 1: Symbol-only
SYM_DIR="/data/rrf-sym"
if is_complete "$SYM_DIR" && [[ "$FORCE" != "true" ]]; then
    echo "Phase 1: $SYM_DIR exists and looks complete, skipping (use --force to overwrite)"
else
    echo "Phase 1: Optimizing symbol-only RRF parameters..."
    poule tune-rrf --db "$DB" --output-dir "$SYM_DIR" --n-trials "$N_TRIALS_SYM" \
        "${DATA_FILES[@]}"
fi

# Phase 2: Combined (symbol + neural)
COMBINED_DIR="/data/rrf-combined"
if is_complete "$COMBINED_DIR" && [[ "$FORCE" != "true" ]]; then
    echo "Phase 2: $COMBINED_DIR exists and looks complete, skipping (use --force to overwrite)"
else
    if [[ ! -f "$CHECKPOINT" ]]; then
        # Fall back to safetensors if .pt not found
        ALT="${CHECKPOINT%.pt}.safetensors"
        if [[ "$CHECKPOINT" == *.pt ]] && [[ -f "$ALT" ]]; then
            CHECKPOINT="$ALT"
            echo "Phase 2: Using $CHECKPOINT (no .pt found)"
        else
            echo "Phase 2: Skipping — no checkpoint at $CHECKPOINT" >&2
            exit 0
        fi
    fi
    echo "Phase 2: Optimizing combined RRF parameters..."
    poule tune-rrf --db "$DB" --output-dir "$COMBINED_DIR" --n-trials "$N_TRIALS_COMBINED" \
        --checkpoint "$CHECKPOINT" "${DATA_FILES[@]}"
fi

echo "Done."
