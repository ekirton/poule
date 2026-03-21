#!/usr/bin/env bash
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
FILE="${FILE#./}"
FILE="${FILE#$PWD/}"

PHASE=$(cat .claude/sdd-layer 2>/dev/null || echo "free")

# Only auto-run pytest during implementation or free phases.
# During tests/specification phases, the skill runs pytest explicitly at checkpoints.
if [ "$PHASE" = "implementation" ] || [ "$PHASE" = "free" ]; then
  if [[ "$FILE" == src/* ]] || [[ "$FILE" == test/* ]]; then
    python -m pytest test/ -x -q 2>&1 | tail -20
  fi
fi

exit 0
