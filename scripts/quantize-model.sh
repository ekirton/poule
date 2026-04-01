#!/usr/bin/env bash
set -euo pipefail

CHECKPOINT="/data/model.pt"
OUTPUT="/data/tactic-predictor.onnx"

usage() {
    echo "Usage: $(basename "$0") [--checkpoint PATH] [--output PATH]" >&2
    echo "" >&2
    echo "Quantize a trained model to INT8 ONNX for CPU inference." >&2
    echo "" >&2
    echo "Options:" >&2
    echo "  --checkpoint   Model checkpoint path (default: $CHECKPOINT)" >&2
    echo "  --output       ONNX output path (default: $OUTPUT)" >&2
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --checkpoint) CHECKPOINT="$2"; shift 2 ;;
        --output) OUTPUT="$2"; shift 2 ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

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

echo "Quantizing $CHECKPOINT -> $OUTPUT"
poule quantize --checkpoint "$CHECKPOINT" --output "$OUTPUT"
