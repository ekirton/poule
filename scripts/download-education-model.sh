#!/usr/bin/env bash
set -euo pipefail

# Download and INT8-quantize the all-MiniLM-L6-v2 model for the textbook RAG.
# Produces: models/education/encoder.onnx (~23MB) and tokenizer.json (~700KB).
#
# Run from the project root:
#   ./scripts/download-education-model.sh
#
# Prerequisites (installed in a temp venv automatically):
#   - optimum (ONNX export)
#   - onnxruntime (quantization)

MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"
OUTPUT_DIR="models/education"
TMP_DIR=$(mktemp -d)

cleanup() {
    rm -rf "$TMP_DIR"
}
trap cleanup EXIT

echo "==> Creating output directory: $OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR"

echo "==> Setting up temporary Python environment"
python3 -m venv "$TMP_DIR/venv"
# shellcheck disable=SC1091
source "$TMP_DIR/venv/bin/activate"
pip install --quiet optimum[exporters] onnxruntime

echo "==> Exporting $MODEL_NAME to ONNX"
optimum-cli export onnx \
    --model "$MODEL_NAME" \
    --task feature-extraction \
    "$TMP_DIR/onnx/"

echo "==> Quantizing to INT8"
python3 -c "
from onnxruntime.quantization import quantize_dynamic, QuantType
quantize_dynamic(
    '$TMP_DIR/onnx/model.onnx',
    '$TMP_DIR/onnx/model_int8.onnx',
    weight_type=QuantType.QInt8,
)
print('Quantization complete')
"

echo "==> Copying model and tokenizer to $OUTPUT_DIR"
cp "$TMP_DIR/onnx/model_int8.onnx" "$OUTPUT_DIR/encoder.onnx"
cp "$TMP_DIR/onnx/tokenizer.json" "$OUTPUT_DIR/tokenizer.json"

# Report sizes
MODEL_SIZE=$(du -h "$OUTPUT_DIR/encoder.onnx" | cut -f1)
TOKENIZER_SIZE=$(du -h "$OUTPUT_DIR/tokenizer.json" | cut -f1)

echo ""
echo "Done:"
echo "  $OUTPUT_DIR/encoder.onnx     ($MODEL_SIZE)"
echo "  $OUTPUT_DIR/tokenizer.json   ($TOKENIZER_SIZE)"
echo ""
echo "Next steps:"
echo "  1. Rebuild the education database:"
echo "     uv run python -m Poule.education.build \\"
echo "         --sf-dir software-foundations \\"
echo "         --output /data/education.db \\"
echo "         --model $OUTPUT_DIR/encoder.onnx \\"
echo "         --tokenizer $OUTPUT_DIR/tokenizer.json"
echo "  2. Rebuild the Docker image: docker build -t poule:latest ."
