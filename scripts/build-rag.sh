#!/usr/bin/env bash
set -euo pipefail

# Download the pre-quantized all-MiniLM-L6-v2 model and build the education
# RAG database from Software Foundations HTML.
#
# Usage:
#   ./scripts/build-rag.sh [--sf-dir DIR] [--output PATH]
#
# Defaults match the Docker layout:
#   --sf-dir   /poule/software-foundations
#   --output   /data/education.db

SF_DIR="/poule/software-foundations"
OUTPUT="/data/education.db"
MODEL_DIR="/data/models/education"

while [[ $# -gt 0 ]]; do
    case $1 in
        --sf-dir)  SF_DIR="$2"; shift 2 ;;
        --output)  OUTPUT="$2"; shift 2 ;;
        *)         echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

MODEL="$MODEL_DIR/encoder.onnx"
TOKENIZER="$MODEL_DIR/tokenizer.json"

# --- Download model files if missing ---
if [[ ! -f "$MODEL" || ! -f "$TOKENIZER" ]]; then
    echo "==> Downloading model files to $MODEL_DIR"
    mkdir -p "$MODEL_DIR"
    curl -fsSL https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/onnx/model_quint8_avx2.onnx \
         -o "$MODEL"
    curl -fsSL https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/main/tokenizer.json \
         -o "$TOKENIZER"
    echo "    encoder.onnx     ($(du -h "$MODEL" | cut -f1))"
    echo "    tokenizer.json   ($(du -h "$TOKENIZER" | cut -f1))"
else
    echo "==> Model files already present in $MODEL_DIR"
fi

# --- Build the education database ---
echo "==> Building education database"
uv run python -m Poule.education.build \
    --sf-dir "$SF_DIR" \
    --output "$OUTPUT" \
    --model "$MODEL" \
    --tokenizer "$TOKENIZER"

echo "==> Done: $OUTPUT"
