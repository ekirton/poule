#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Skip if no file path (e.g. Write to stdout)
[ -z "$FILE" ] && exit 0

PHASE=$(cat $CLAUDE_PROJECT_DIR/sdd-layer 2>/dev/null || echo "free")

# Normalize: strip leading ./ or absolute project root prefix
FILE="${FILE#./}"
FILE="${FILE#$PWD/}"

# Helper: check if file is under a given prefix
under() { [[ "$FILE" == "$1"* ]]; }

# SDD-managed directories — only these are subject to phase locking.
# Everything else (doc/plan/, doc/background/, scripts/, commands/, .claude/, etc.)
# is always writable regardless of phase.
is_sdd() {
  under "doc/requirements/" || under "doc/features/" || under "doc/architecture/" \
    || under "specification/" || under "src/" || under "test/"
}

# If the file is not in an SDD-managed directory, allow it unconditionally.
is_sdd || exit 0

case "$PHASE" in
  requirements)
    if ! under "doc/requirements/"; then
      echo "REQUIREMENTS phase: only doc/requirements/ may be edited (among SDD layers). Use /free to unlock." >&2
      exit 2
    fi
    ;;
  features)
    if ! under "doc/features/"; then
      echo "FEATURES phase: only doc/features/ may be edited (among SDD layers). Use /free to unlock." >&2
      exit 2
    fi
    ;;
  architecture)
    if ! under "doc/architecture/"; then
      echo "ARCHITECTURE phase: only doc/architecture/ may be edited (among SDD layers). Use /free to unlock." >&2
      exit 2
    fi
    ;;
  specification)
    if ! under "specification/"; then
      echo "SPECIFICATION phase: only specification/ may be edited (among SDD layers). Use /free to unlock." >&2
      exit 2
    fi
    ;;
  tests)
    if ! under "test/"; then
      echo "TESTS phase: only test/ may be edited (among SDD layers). Use /free to unlock." >&2
      exit 2
    fi
    ;;
  implementation)
    if ! under "src/"; then
      echo "IMPLEMENTATION phase: only src/ may be edited (among SDD layers). File feedback instead. Use /free to unlock." >&2
      exit 2
    fi
    ;;
  free)
    # No restrictions
    ;;
  *)
    echo "Unknown SDD phase '$PHASE'. Valid: requirements, features, architecture, specification, tests, implementation, free" >&2
    exit 2
    ;;
esac

exit 0
