#!/usr/bin/env bash
set -euo pipefail

# One-time migration: compute neural embeddings for existing per-library
# index databases that were built before the embedding step was added
# to build-indexes.sh. Run this once, then re-run publish-indexes.sh
# to merge and generate the FAISS sidecar.
#
# Usage:
#   ./scripts/migrate-index.sh                  # default: all index-*.db in /data
#   ./scripts/migrate-index.sh /path/to/dir     # all index-*.db in dir

INPUT_DIR="${1:-/data}"
MODEL_DIR="${POULE_MODEL_DIR:-${HOME}/.local/share/poule/models}"
MODEL_PATH="${MODEL_DIR}/neural-premise-selector.onnx"
VOCAB_PATH="${MODEL_DIR}/coq-vocabulary.json"

if [[ ! -f "$MODEL_PATH" ]]; then
    echo "Error: model checkpoint not found at $MODEL_PATH" >&2
    echo "Download or train a model first." >&2
    exit 1
fi

# Collect per-library database files
DB_FILES=()
while IFS= read -r -d '' f; do
    DB_FILES+=("$f")
done < <(find "$INPUT_DIR" -maxdepth 1 -name 'index-*.db' -print0 2>/dev/null)

if [[ ${#DB_FILES[@]} -eq 0 ]]; then
    echo "No index-*.db files found in $INPUT_DIR" >&2
    exit 0
fi

migrated=0
skipped=0
failed=0

for db in "${DB_FILES[@]}"; do
    name=$(basename "$db")
    # Check if embeddings already exist
    count=$(sqlite3 "$db" "SELECT COUNT(*) FROM embeddings" 2>/dev/null || echo "0")
    if [[ "$count" -gt 0 ]]; then
        echo "SKIP  $name ($count embeddings already present)"
        ((skipped++))
        continue
    fi

    echo -n "EMBED  $name ... "
    if python -c "
from pathlib import Path
from Poule.neural.encoder import NeuralEncoder
from Poule.neural.embeddings import compute_embeddings

vocab = Path('${VOCAB_PATH}') if Path('${VOCAB_PATH}').exists() else None
encoder = NeuralEncoder.load(Path('${MODEL_PATH}'), vocabulary_path=vocab)
compute_embeddings(Path('${db}'), encoder)
" 2>&1; then
        new_count=$(sqlite3 "$db" "SELECT COUNT(*) FROM embeddings" 2>/dev/null || echo "?")
        echo "OK ($new_count embeddings)"
        ((migrated++))
    else
        echo "FAILED"
        ((failed++))
    fi
done

echo ""
echo "Done: $migrated migrated, $skipped skipped, $failed failed"
echo ""
echo "Next: run ./scripts/publish-indexes.sh to merge and generate FAISS sidecar."
[[ $failed -eq 0 ]]
