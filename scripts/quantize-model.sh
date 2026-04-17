#!/usr/bin/env bash
set -euo pipefail

# Default paths work locally (~/poule-home/data).
# Override with POULE_DATA_DIR or --checkpoint/--output flags.
DATA_DIR="${POULE_DATA_DIR:-${HOME}/poule-home/data}"
CHECKPOINT="${DATA_DIR}/final-model/model.pt"
OUTPUT="${DATA_DIR}/final-model/tactic-predictor.onnx"

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
    echo "Error: checkpoint not found at $CHECKPOINT" >&2
    exit 1
fi

echo "Quantizing $CHECKPOINT -> $OUTPUT"
python -c "
from pathlib import Path
from Poule.neural.training.quantizer import ModelQuantizer
ModelQuantizer.quantize(Path('${CHECKPOINT}'), Path('${OUTPUT}'))
print('Done.')
"
