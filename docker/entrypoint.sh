#!/bin/bash
set -euo pipefail

# ── Claude Code symlinks ─────────────────────────────────────────────────────
# Symlink baked-in Claude Code from /opt into the persistent home so it
# appears on PATH even when ~/poule-home is bind-mounted over $HOME.
mkdir -p "$HOME/.local/bin" "$HOME/.local/share"
ln -sf "$(ls -d /opt/claude/versions/* | head -1)" "$HOME/.local/bin/claude"
ln -sf /opt/claude "$HOME/.local/share/claude"

# ── Slash commands ────────────────────────────────────────────────────────────
# Symlink each baked-in slash command individually so user-added commands
# in the persistent home are preserved.
COMMANDS_SRC="/poule/commands"
COMMANDS_DST="$HOME/.claude/commands"
if [ -d "$COMMANDS_SRC" ]; then
    mkdir -p "$COMMANDS_DST"
    for f in "$COMMANDS_SRC"/*.md; do
        [ -f "$f" ] || continue
        base=$(basename "$f")
        [ "$base" = "CLAUDE.md" ] && continue
        ln -sf "$f" "$COMMANDS_DST/$base"
    done
fi

# ── MCP config ──────────────────────────────────────────────────────────
# Claude Code discovers MCP servers via .mcp.json in the working directory.
# Copy the baked-in config so it's present regardless of where Claude runs.
if [ ! -f .mcp.json ] && [ -f /poule/.mcp.json ]; then
    cp /poule/.mcp.json .mcp.json
fi

# ── MCP server lifecycle ─────────────────────────────────────────────────────
# Start the MCP server and ensure it stops when the container exits.
cleanup() {
    poule-mcp stop 2>/dev/null || true
}
trap cleanup EXIT INT TERM

poule-mcp start

if [ $# -gt 0 ]; then
    "$@"
else
    # Default: launch Claude Code (Opus).
    claude --dangerously-skip-permissions --model opus
fi
