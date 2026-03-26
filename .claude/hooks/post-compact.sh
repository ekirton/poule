#!/usr/bin/env bash
PHASE=$(cat $CLAUDE_PROJECT_DIR/sdd-layer 2>/dev/null || echo "free")
if [ "$PHASE" != "free" ]; then
  echo "SDD phase: $PHASE. Layer enforcement is active."
  echo "Use /free to disable, or the appropriate phase command to switch."
fi
