#!/usr/bin/env bash
#
# Publish a prebuilt index.db (and optionally an ONNX model) as a GitHub Release.
#
# Usage:
#   ./scripts/publish-release.sh index.db
#   ./scripts/publish-release.sh index.db --model models/neural-premise-selector.onnx
#
# Prerequisites: gh (authenticated), sqlite3, shasum

set -euo pipefail

usage() {
    echo "Usage: $0 DB_PATH [--model MODEL_PATH]"
    echo
    echo "Publish a prebuilt index database as a GitHub Release."
    echo
    echo "Arguments:"
    echo "  DB_PATH              Path to the index.db file"
    echo
    echo "Options:"
    echo "  --model MODEL_PATH   Also upload an ONNX model file"
    exit 1
}

# --- Parse arguments ---

DB_PATH=""
MODEL_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            MODEL_PATH="$2"
            shift 2
            ;;
        --help|-h)
            usage
            ;;
        *)
            if [[ -z "$DB_PATH" ]]; then
                DB_PATH="$1"
                shift
            else
                echo "Error: unexpected argument '$1'"
                usage
            fi
            ;;
    esac
done

if [[ -z "$DB_PATH" ]]; then
    echo "Error: DB_PATH is required."
    usage
fi

# --- Validate prerequisites ---

if ! command -v gh &>/dev/null; then
    echo "Error: gh CLI not found. Install from https://cli.github.com/"
    exit 1
fi

if ! gh auth status &>/dev/null; then
    echo "Error: gh not authenticated. Run 'gh auth login' first."
    exit 1
fi

if ! command -v sqlite3 &>/dev/null; then
    echo "Error: sqlite3 not found."
    exit 1
fi

if ! command -v shasum &>/dev/null; then
    echo "Error: shasum not found."
    exit 1
fi

if [[ ! -f "$DB_PATH" ]]; then
    echo "Error: $DB_PATH does not exist."
    exit 1
fi

if [[ -n "$MODEL_PATH" && ! -f "$MODEL_PATH" ]]; then
    echo "Error: $MODEL_PATH does not exist."
    exit 1
fi

# --- Read version metadata from index_meta ---

schema_version=$(sqlite3 "$DB_PATH" "SELECT value FROM index_meta WHERE key='schema_version'")
coq_version=$(sqlite3 "$DB_PATH" "SELECT value FROM index_meta WHERE key='coq_version'")
mathcomp_version=$(sqlite3 "$DB_PATH" "SELECT value FROM index_meta WHERE key='mathcomp_version'")
created_at=$(sqlite3 "$DB_PATH" "SELECT value FROM index_meta WHERE key='created_at'")

if [[ -z "$schema_version" || -z "$coq_version" || -z "$mathcomp_version" ]]; then
    echo "Error: could not read version metadata from index_meta table."
    exit 1
fi

echo "Index metadata:"
echo "  schema_version:  $schema_version"
echo "  coq_version:     $coq_version"
echo "  mathcomp_version: $mathcomp_version"
echo "  created_at:      $created_at"

# --- Compute checksums ---

db_sha256=$(shasum -a 256 "$DB_PATH" | awk '{print $1}')
echo "  index.db SHA-256: $db_sha256"

onnx_sha256="null"
if [[ -n "$MODEL_PATH" ]]; then
    onnx_sha256="\"$(shasum -a 256 "$MODEL_PATH" | awk '{print $1}')\""
    echo "  ONNX SHA-256:    $onnx_sha256"
fi

# --- Generate manifest.json ---

manifest_tmp=$(mktemp /tmp/manifest.XXXXXX.json)
cat > "$manifest_tmp" <<EOF
{
  "schema_version": "$schema_version",
  "coq_version": "$coq_version",
  "mathcomp_version": "$mathcomp_version",
  "index_db_sha256": "$db_sha256",
  "onnx_model_sha256": $onnx_sha256,
  "created_at": "$created_at"
}
EOF

echo
echo "Generated manifest.json:"
cat "$manifest_tmp"
echo

# --- Construct tag ---

tag="index-v${schema_version}-coq${coq_version}-mc${mathcomp_version}"
echo "Release tag: $tag"

# Check if tag already exists
if gh release view "$tag" &>/dev/null; then
    echo "Error: Release $tag already exists. Delete it first or use a different version."
    rm -f "$manifest_tmp"
    exit 1
fi

# --- Create release ---

assets=("$DB_PATH#index.db" "$manifest_tmp#manifest.json")
if [[ -n "$MODEL_PATH" ]]; then
    assets+=("$MODEL_PATH#neural-premise-selector.onnx")
fi

gh release create "$tag" \
    "${assets[@]}" \
    --title "Index: Coq ${coq_version} + MathComp ${mathcomp_version}" \
    --notes "Prebuilt search index for Coq ${coq_version} with MathComp ${mathcomp_version} (schema v${schema_version})."

rm -f "$manifest_tmp"

echo
echo "Release created: $tag"
echo "URL: $(gh release view "$tag" --json url --jq .url)"
