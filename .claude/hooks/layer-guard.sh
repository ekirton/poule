#!/usr/bin/env bash
set -euo pipefail

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Skip if no file path (e.g. Write to stdout)
[ -z "$FILE" ] && exit 0

PHASE=$(cat .claude/sdd-layer 2>/dev/null || echo "free")

# Normalize: strip leading ./ or absolute project root prefix
FILE="${FILE#./}"
FILE="${FILE#$PWD/}"

# Helper: check if file is under a given prefix
under() { [[ "$FILE" == "$1"* ]]; }

case "$PHASE" in
  requirements)
    if ! under "doc/requirements/"; then
      echo "REQUIREMENTS phase: only doc/requirements/ may be edited. Use /free to unlock." >&2
      exit 2
    fi
    ;;
  features)
    if ! under "doc/features/"; then
      echo "FEATURES phase: only doc/features/ may be edited. Use /free to unlock." >&2
      exit 2
    fi
    ;;
  architecture)
    if ! under "doc/architecture/"; then
      echo "ARCHITECTURE phase: only doc/architecture/ may be edited. Use /free to unlock." >&2
      exit 2
    fi
    ;;
  specification)
    if ! under "specification/"; then
      echo "SPECIFICATION phase: only specification/ may be edited. Use /free to unlock." >&2
      exit 2
    fi
    ;;
  tests)
    if ! under "test/"; then
      echo "TESTS phase: only test/ may be edited. Use /free to unlock." >&2
      exit 2
    fi
    ;;
  implementation)
    if under "test/" || under "specification/" || under "doc/"; then
      echo "IMPLEMENTATION phase: only src/, commands/, and tasks/ may be edited. Do not change tests or upstream layers. File feedback instead. Use /free to unlock." >&2
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
