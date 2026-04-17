#!/usr/bin/env bash
#
# Publish quantized tactic prediction model as a GitHub Release:
#   tactic-model — tactic-predictor.onnx + tactic-labels.json
#                  + tokenizer.model + manifest.json
#
# There is always exactly one release; the existing one is replaced.
#
# Usage:
#   ./scripts/publish-model.sh [--model-dir DIR]
#
# Prerequisites: gh (authenticated), shasum
# Run ./scripts/quantize-model.sh first to produce the ONNX model.

set -euo pipefail

DATA_DIR="${POULE_DATA_DIR:-${HOME}/poule-home/data}"
MODEL_DIR="${DATA_DIR}/final-model"
TAG="tactic-model"

usage() {
    echo "Usage: $0 [--model-dir DIR]"
    echo
    echo "Publish the quantized tactic prediction model as a GitHub Release."
    echo
    echo "Options:"
    echo "  --model-dir  Directory containing model artifacts (default: ${MODEL_DIR})"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model-dir) MODEL_DIR="$2"; shift 2 ;;
        --help|-h) usage ;;
        *) echo "Unknown option: $1" >&2; usage ;;
    esac
done

# --- Validate prerequisites ---

for cmd in gh shasum; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: ${cmd} not found." >&2
        exit 1
    fi
done

if ! gh auth status &>/dev/null; then
    echo "Error: gh not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi

# --- Validate model artifacts exist ---

ONNX_PATH="${MODEL_DIR}/tactic-predictor.onnx"
LABELS_PATH="${MODEL_DIR}/tactic-labels.json"
VOCAB_PATH="${MODEL_DIR}/vocabulary/tokenizer.model"

for f in "$ONNX_PATH" "$LABELS_PATH" "$VOCAB_PATH"; do
    if [[ ! -f "$f" ]]; then
        echo "Error: ${f} does not exist." >&2
        echo "Run ./scripts/quantize-model.sh first." >&2
        exit 1
    fi
done

# --- Compute checksums ---

onnx_sha=$(shasum -a 256 "$ONNX_PATH" | awk '{print $1}')
labels_sha=$(shasum -a 256 "$LABELS_PATH" | awk '{print $1}')
vocab_sha=$(shasum -a 256 "$VOCAB_PATH" | awk '{print $1}')

onnx_size=$(stat -c%s "$ONNX_PATH" 2>/dev/null || stat -f%z "$ONNX_PATH")
labels_size=$(stat -c%s "$LABELS_PATH" 2>/dev/null || stat -f%z "$LABELS_PATH")
vocab_size=$(stat -c%s "$VOCAB_PATH" 2>/dev/null || stat -f%z "$VOCAB_PATH")

echo "Model artifacts:"
printf "  %-28s %s bytes  (SHA-256: %s)\n" "tactic-predictor.onnx" "$onnx_size" "$onnx_sha"
printf "  %-28s %s bytes  (SHA-256: %s)\n" "tactic-labels.json" "$labels_size" "$labels_sha"
printf "  %-28s %s bytes  (SHA-256: %s)\n" "tokenizer.model" "$vocab_size" "$vocab_sha"

# --- Read label count for release notes ---

label_count=$(python3 -c "import json; print(len(json.load(open('${LABELS_PATH}'))))")

created_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# --- Generate manifest ---

manifest_tmp=$(mktemp /tmp/manifest-model.XXXXXX.json)

cat > "$manifest_tmp" <<EOF
{
  "created_at": "$created_at",
  "artifacts": {
    "tactic-predictor.onnx": {
      "sha256": "$onnx_sha",
      "size": $onnx_size,
      "description": "FP32 ONNX tactic family classifier"
    },
    "tactic-labels.json": {
      "sha256": "$labels_sha",
      "size": $labels_size,
      "description": "Ordered tactic family names (index to name)"
    },
    "tokenizer.model": {
      "sha256": "$vocab_sha",
      "size": $vocab_size,
      "description": "SentencePiece BPE tokenizer model"
    }
  },
  "label_count": $label_count
}
EOF

echo
echo "Generated manifest."

# --- Delete existing release ---

if gh release view "$TAG" &>/dev/null; then
    echo "Deleting existing release ${TAG}..."
    gh release delete "$TAG" --yes --cleanup-tag
fi
git tag -d "$TAG" 2>/dev/null || true
git push origin ":refs/tags/${TAG}" 2>/dev/null || true

# --- Stage assets in a temp directory ---

upload_dir=$(mktemp -d /tmp/poule-publish-model.XXXXXX)
cp "$ONNX_PATH" "$upload_dir/tactic-predictor.onnx"
cp "$LABELS_PATH" "$upload_dir/tactic-labels.json"
cp "$VOCAB_PATH" "$upload_dir/tokenizer.model"
cp "$manifest_tmp" "$upload_dir/manifest.json"

assets=(
    "$upload_dir/tactic-predictor.onnx"
    "$upload_dir/tactic-labels.json"
    "$upload_dir/tokenizer.model"
    "$upload_dir/manifest.json"
)

# --- Create release ---

echo "Creating release: ${TAG}"

gh release create "$TAG" \
    "${assets[@]}" \
    --title "Tactic prediction model (${label_count} families)" \
    --notes "FP32 ONNX tactic family classifier with ${label_count} tactic families. Download with: poule download-index --include-model"

# --- Cleanup ---

rm -rf "$manifest_tmp" "$upload_dir"

echo
echo "Release created:"
echo "  ${TAG}: $(gh release view "$TAG" --json url --jq .url)"
