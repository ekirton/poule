#!/usr/bin/env bash
#
# Publish index databases as two GitHub Releases:
#   index-libraries  — 6 per-library index-*.db files + manifest.json
#   index-merged     — single merged index.db + manifest.json
#
# There are always exactly two releases; existing ones are replaced.
#
# Usage:
#   ./scripts/publish-indexes.sh
#
# Prerequisites: gh (authenticated), sqlite3, shasum
# Run ./scripts/build-indexes.sh first to build the indexes.

set -euo pipefail

LIBRARIES="stdlib mathcomp stdpp flocq coquelicot coqinterval"
INPUT_DIR="/data"
TAG_LIBRARIES="index-libraries"
TAG_MERGED="index-merged"

usage() {
    echo "Usage: $0"
    echo
    echo "Publish index databases as two GitHub Releases:"
    echo "  ${TAG_LIBRARIES}  — per-library index-*.db files + manifest"
    echo "  ${TAG_MERGED}     — merged index.db + manifest"
    exit 1
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            ;;
    esac
done

# --- Validate prerequisites ---

for cmd in gh sqlite3 shasum; do
    if ! command -v "$cmd" &>/dev/null; then
        echo "Error: ${cmd} not found." >&2
        exit 1
    fi
done

if ! gh auth status &>/dev/null; then
    echo "Error: gh not authenticated. Run 'gh auth login' first." >&2
    exit 1
fi

# --- Validate files exist ---

DB_PATHS=()
for lib in $LIBRARIES; do
    db="${INPUT_DIR}/index-${lib}.db"
    if [[ ! -f "$db" ]]; then
        echo "Error: ${db} does not exist." >&2
        exit 1
    fi
    DB_PATHS+=("$db")
done

INDEX_DB="${INPUT_DIR}/index.db"

# --- Merge per-library indexes into index.db (if needed) ---

NEED_MERGE=false
LIB_LIST="$LIBRARIES"

if [[ ! -f "$INDEX_DB" ]]; then
    NEED_MERGE=true
else
    # Compare library_versions in index.db against per-library index versions
    merged_versions=$(sqlite3 "$INDEX_DB" "SELECT value FROM index_meta WHERE key = 'library_versions'" 2>/dev/null || true)
    if [[ -z "$merged_versions" ]]; then
        NEED_MERGE=true
    else
        for lib in $LIBRARIES; do
            per_lib_ver=""
            per_lib_db="${INPUT_DIR}/index-${lib}.db"
            if [[ -f "$per_lib_db" ]]; then
                per_lib_ver=$(sqlite3 "$per_lib_db" "SELECT value FROM index_meta WHERE key = 'library_version'" 2>/dev/null || true)
            fi
            merged_lib_ver=$(python -c "import json,sys; d=json.loads(sys.argv[1]); print(d.get(sys.argv[2],''))" "$merged_versions" "$lib")
            if [[ "$per_lib_ver" != "$merged_lib_ver" ]]; then
                echo "index.db out of date: ${lib} ${merged_lib_ver} -> ${per_lib_ver}" >&2
                NEED_MERGE=true
            fi
        done
    fi
fi

if [[ "$NEED_MERGE" == true ]]; then
    echo "Merging per-library indexes into ${INDEX_DB}..."
    python -c "
from pathlib import Path
from Poule.storage.merge import merge_indexes

sources = []
for lib in '${LIB_LIST}'.split():
    sources.append((lib, Path('${INPUT_DIR}') / f'index-{lib}.db'))

result = merge_indexes(sources, Path('${INDEX_DB}'))

print(f'  Declarations: {result[\"total_declarations\"]}')
print(f'  Dependencies: {result[\"total_dependencies\"]}')
print(f'  Dropped deps: {result[\"dropped_dependencies\"]}')
print(f'  Libraries:    {\", \".join(result[\"libraries\"])}')
"
    echo
else
    echo "index.db is up to date."
fi

# --- Read version metadata from per-library DBs ---

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
        echo "Error: could not read version metadata from index_meta table in ${db_path}." >&2
        exit 1
    fi

    if [[ -z "$FIRST_DB" ]]; then
        FIRST_DB="$db_path"
        REF_SCHEMA_VERSION="$schema_version"
        REF_COQ_VERSION="$coq_version"
    else
        if [[ "$schema_version" != "$REF_SCHEMA_VERSION" ]]; then
            echo "Error: schema version mismatch: ${FIRST_DB} has ${REF_SCHEMA_VERSION}, ${db_path} has ${schema_version}." >&2
            exit 1
        fi
        if [[ "$coq_version" != "$REF_COQ_VERSION" ]]; then
            echo "Error: Coq version mismatch: ${FIRST_DB} has ${REF_COQ_VERSION}, ${db_path} has ${coq_version}." >&2
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

index_sha=$(shasum -a 256 "$INDEX_DB" | awk '{print $1}')
index_decls=$(sqlite3 "$INDEX_DB" "SELECT value FROM index_meta WHERE key='declarations'" 2>/dev/null \
    || sqlite3 "$INDEX_DB" "SELECT COUNT(*) FROM declarations" 2>/dev/null || echo "?")
printf "  %-16s          (%s declarations, SHA-256: %s)\n" "index.db:" "$index_decls" "$index_sha"

# --- Build library list string ---

lib_list=""
for i in "${!LIB_NAMES[@]}"; do
    if [[ $i -gt 0 ]]; then
        lib_list+=", "
    fi
    lib_list+="${LIB_NAMES[$i]} ${LIB_VERSIONS[$i]}"
done

created_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# --- Generate libraries manifest ---

libraries_manifest_tmp=$(mktemp /tmp/manifest-libraries.XXXXXX.json)

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

cat > "$libraries_manifest_tmp" <<EOF
{
  "schema_version": "$REF_SCHEMA_VERSION",
  "coq_version": "$REF_COQ_VERSION",
  "created_at": "$created_at",
  "libraries": $libraries_json
}
EOF

# --- Generate merged manifest ---

merged_manifest_tmp=$(mktemp /tmp/manifest-merged.XXXXXX.json)

cat > "$merged_manifest_tmp" <<EOF
{
  "schema_version": "$REF_SCHEMA_VERSION",
  "coq_version": "$REF_COQ_VERSION",
  "created_at": "$created_at",
  "index": {
    "sha256": "$index_sha",
    "asset_name": "index.db"
  },
  "libraries": $libraries_json
}
EOF

echo
echo "Generated manifests."
echo

# --- Delete existing releases ---

for old_tag in "$TAG_LIBRARIES" "$TAG_MERGED"; do
    if gh release view "$old_tag" &>/dev/null; then
        echo "Deleting existing release ${old_tag}..."
        gh release delete "$old_tag" --yes --cleanup-tag
    fi
    # Remove any lingering local or remote tag
    git tag -d "$old_tag" 2>/dev/null || true
    git push origin ":refs/tags/${old_tag}" 2>/dev/null || true
done

# --- Create libraries release ---

echo "Creating release: ${TAG_LIBRARIES}"

# Stage assets in a temp directory with correct filenames (gh release create
# #displayname syntax is unreliable across gh versions).
upload_dir=$(mktemp -d /tmp/poule-publish.XXXXXX)

lib_assets=()
for i in "${!DB_PATHS[@]}"; do
    cp "${DB_PATHS[$i]}" "$upload_dir/index-${LIB_NAMES[$i]}.db"
    lib_assets+=("$upload_dir/index-${LIB_NAMES[$i]}.db")
done
cp "$libraries_manifest_tmp" "$upload_dir/manifest.json"
lib_assets+=("$upload_dir/manifest.json")

gh release create "$TAG_LIBRARIES" \
    "${lib_assets[@]}" \
    --title "Per-library indexes: Coq ${REF_COQ_VERSION} (${lib_list})" \
    --notes "Per-library search indexes for Coq ${REF_COQ_VERSION} (schema v${REF_SCHEMA_VERSION}). Libraries: ${lib_list}."

# --- Create merged release ---

echo "Creating release: ${TAG_MERGED}"

# Re-stage manifest for merged release (separate copy to avoid conflicts)
merged_upload_dir=$(mktemp -d /tmp/poule-publish-merged.XXXXXX)
cp "${INDEX_DB}" "$merged_upload_dir/index.db"
cp "$merged_manifest_tmp" "$merged_upload_dir/manifest.json"
merged_assets=("$merged_upload_dir/index.db" "$merged_upload_dir/manifest.json")

gh release create "$TAG_MERGED" \
    "${merged_assets[@]}" \
    --title "Merged index: Coq ${REF_COQ_VERSION} (${lib_list})" \
    --notes "Merged search index for Coq ${REF_COQ_VERSION} (schema v${REF_SCHEMA_VERSION}). Libraries: ${lib_list}."

# --- Cleanup ---

rm -rf "$libraries_manifest_tmp" "$merged_manifest_tmp" "$upload_dir" "$merged_upload_dir"

echo
echo "Releases created:"
echo "  ${TAG_LIBRARIES}: $(gh release view "$TAG_LIBRARIES" --json url --jq .url)"
echo "  ${TAG_MERGED}:    $(gh release view "$TAG_MERGED" --json url --jq .url)"
