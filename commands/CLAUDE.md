## Slash Command Prompt Files

**Layer:** 5 — Implementation

**Location:** `commands/<command-name>.md`

**Derived from:** `doc/features/<command-name>.md`

**Authority:** Command prompt files are the **executable implementation** of agentic workflow features. They are authoritative for Claude's runtime behavior when the corresponding slash command is invoked. They are not authoritative for what the feature does or why — that belongs in the feature document.

**Before writing or editing command files:**

1. Read the upstream feature document this command implements.
2. Read the feature's acceptance criteria.
3. Verify the command's scope is consistent with the feature's stated scope boundaries.

**When writing or editing command files:**

- Write as **direct instructions to Claude** — imperative, second-person ("Search for...", "Open a proof session on...").
- Do not include frontmatter, metadata, or document headers beyond a brief one-line description of the command.
- Specify **which tools to use** at each step. See [doc/MCP_TOOLS.md](../doc/MCP_TOOLS.md) for the full MCP tool inventory. Standard Claude Code tools (Read, Write, Edit, Grep, Glob, Bash) are also available.
- Structure as **numbered steps** for the primary workflow.
- Include **decision points** — when to branch, retry, or fall back to alternative strategies.
- Include an **edge cases** section covering empty input, missing prerequisites, and large-scale operation.
- Specify the **output format** — what the user sees when the command completes.
- Always instruct Claude to **clean up resources** (close proof sessions, etc.) before finishing.
- Do not re-state what or why — only how. Reference the feature document for rationale.
- Do not include motivational text, background context, or prose that does not directly instruct Claude's behavior.

**Naming convention:** The filename (minus `.md`) is the slash command name. `/proof-repair` → `proof-repair.md`.

**One per:** slash command
