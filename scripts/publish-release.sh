#!/usr/bin/env bash
#
# Publish per-library prebuilt index databases (and optionally an ONNX model)
# as a GitHub Release.
#
# Usage:
#   ./scripts/publish-release.sh index-stdlib.db index-mathcomp.db ...
#   ./scripts/publish-release.sh index-stdlib.db --model models/neural-premise-selector.onnx
#
# Prerequisites: gh (authenticated), sqlite3, shasum

set -euo pipefail

usage() {
    echo "Usage: $0 DB_PATH [DB_PATH ...] [--model MODEL_PATH]"
    echo
    echo "Publish per-library prebuilt index databases as a GitHub Release."
    echo
    echo "Arguments:"
    echo "  DB_PATH              One or more per-library index-*.db files"
    echo
    echo "Options:"
    echo "  --model MODEL_PATH   Also upload an ONNX model file"
    exit 1
}

# --- Parse arguments ---

DB_PATHS=()
MODEL_PATH=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)
            if [[ $# -lt 2 ]]; then
                echo "Error: --model requires a path argument."
                usage
            fi
            MODEL_PATH="$2"
            shift 2
            ;;
        --help|-h)
            usage
            ;;
        *)
            DB_PATHS+=("$1")
            shift
            ;;
    esac
done

if [[ ${#DB_PATHS[@]} -eq 0 ]]; then
    echo "Error: at least one DB_PATH is required."
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

# --- Validate files exist ---

for db_path in "${DB_PATHS[@]}"; do
    if [[ ! -f "$db_path" ]]; then
        echo "Error: ${db_path} does not exist."
        exit 1
    fi
done

if [[ -n "$MODEL_PATH" && ! -f "$MODEL_PATH" ]]; then
    echo "Error: ${MODEL_PATH} does not exist."
    exit 1
fi

# --- Read version metadata from each DB ---

# Arrays to hold per-library metadata
declare -a LIB_NAMES=()
declare -a LIB_VERSIONS=()
declare -a LIB_DECLARATIONS=()
declare -a LIB_SHA256=()

FIRST_DB=""
REF_SCHEMA_VERSION=""
REF_COQ_VERSION=""

for db_path in "${DB_PATHS[@]}"; do
    schema_version=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key='schema_version'" 2>/dev/null || true)
    coq_version=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key='coq_version'" 2>/dev/null || true)
    library=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key='library'" 2>/dev/null || true)
    library_version=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key='library_version'" 2>/dev/null || true)
    declarations=$(sqlite3 "$db_path" "SELECT value FROM index_meta WHERE key='declarations'" 2>/dev/null || true)

    if [[ -z "$schema_version" || -z "$coq_version" || -z "$library" || -z "$library_version" || -z "$declarations" ]]; then
        echo "Error: could not read version metadata from index_meta table in ${db_path}."
        exit 1
    fi

    # Verify consistency across databases
    if [[ -z "$FIRST_DB" ]]; then
        FIRST_DB="$db_path"
        REF_SCHEMA_VERSION="$schema_version"
        REF_COQ_VERSION="$coq_version"
    else
        if [[ "$schema_version" != "$REF_SCHEMA_VERSION" ]]; then
            echo "Error: schema version mismatch: ${FIRST_DB} has ${REF_SCHEMA_VERSION}, ${db_path} has ${schema_version}."
            exit 1
        fi
        if [[ "$coq_version" != "$REF_COQ_VERSION" ]]; then
            echo "Error: Coq version mismatch: ${FIRST_DB} has ${REF_COQ_VERSION}, ${db_path} has ${coq_version}."
            exit 1
        fi
    fi

    LIB_NAMES+=("$library")
    LIB_VERSIONS+=("$library_version")
    LIB_DECLARATIONS+=("$declarations")
done

echo "Index metadata:"
echo "  schema_version:  $REF_SCHEMA_VERSION"
echo "  coq_version:     $REF_COQ_VERSION"
echo "Libraries:"

# --- Compute checksums ---

for i in "${!DB_PATHS[@]}"; do
    sha=$(shasum -a 256 "${DB_PATHS[$i]}" | awk '{print $1}')
    LIB_SHA256+=("$sha")
    printf "  %-16s %s  (%s declarations, SHA-256: %s)\n" "${LIB_NAMES[$i]}:" "${LIB_VERSIONS[$i]}" "${LIB_DECLARATIONS[$i]}" "$sha"
done

onnx_sha256="null"
if [[ -n "$MODEL_PATH" ]]; then
    onnx_sha256=$(shasum -a 256 "$MODEL_PATH" | awk '{print $1}')
    printf "  %-16s          (SHA-256: %s)\n" "ONNX model:" "$onnx_sha256"
fi

# --- Generate manifest.json ---

manifest_tmp=$(mktemp /tmp/manifest.XXXXXX.json)

created_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Build the libraries JSON object
libraries_json="{"
for i in "${!LIB_NAMES[@]}"; do
    if [[ $i -gt 0 ]]; then
        libraries_json+=","
    fi
    libraries_json+="
    \"${LIB_NAMES[$i]}\": {
      \"version\": \"${LIB_VERSIONS[$i]}\",
      \"sha256\": \"${LIB_SHA256[$i]}\",
      \"asset_name\": \"index-${LIB_NAMES[$i]}.db\",
      \"declarations\": ${LIB_DECLARATIONS[$i]}
    }"
done
libraries_json+="
  }"

# Format onnx_model_sha256 as JSON
if [[ "$onnx_sha256" == "null" ]]; then
    onnx_json="null"
else
    onnx_json="\"$onnx_sha256\""
fi

cat > "$manifest_tmp" <<EOF
{
  "schema_version": "$REF_SCHEMA_VERSION",
  "coq_version": "$REF_COQ_VERSION",
  "created_at": "$created_at",
  "libraries": $libraries_json,
  "onnx_model_sha256": $onnx_json
}
EOF

echo
echo "Generated manifest.json:"
cat "$manifest_tmp"
echo

# --- Construct tag ---

tag="index-v${REF_SCHEMA_VERSION}-coq${REF_COQ_VERSION}"
echo "Release tag: $tag"

# Check if tag already exists
if gh release view "$tag" &>/dev/null; then
    echo "Error: Release ${tag} already exists. Delete it first or use a different version."
    rm -f "$manifest_tmp"
    exit 1
fi

# --- Create release ---

assets=()
for i in "${!DB_PATHS[@]}"; do
    assets+=("${DB_PATHS[$i]}#index-${LIB_NAMES[$i]}.db")
done
assets+=("$manifest_tmp#manifest.json")

if [[ -n "$MODEL_PATH" ]]; then
    assets+=("$MODEL_PATH#neural-premise-selector.onnx")
fi

# Build title listing all libraries
lib_list=""
for i in "${!LIB_NAMES[@]}"; do
    if [[ $i -gt 0 ]]; then
        lib_list+=", "
    fi
    lib_list+="${LIB_NAMES[$i]} ${LIB_VERSIONS[$i]}"
done

gh release create "$tag" \
    "${assets[@]}" \
    --title "Index: Coq ${REF_COQ_VERSION} (${lib_list})" \
    --notes "Prebuilt search index for Coq ${REF_COQ_VERSION} (schema v${REF_SCHEMA_VERSION}). Libraries: ${lib_list}."

rm -f "$manifest_tmp"

echo
echo "Release created: $tag"
echo "URL: $(gh release view "$tag" --json url --jq .url)"
