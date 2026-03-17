## Slash Command Prompt Files

**Layer:** 5 — Implementation

**Location:** `commands/<command-name>.md`

**Derived from:** `doc/features/<command-name>.md`, `doc/requirements/stories/<command-name>.md`

**Authority:** Command prompt files are the **executable implementation** of agentic workflow features. They are authoritative for Claude's runtime behavior when the corresponding slash command is invoked. They are not authoritative for what the feature does or why — that belongs in the feature document.

**Before writing or editing command files:**

1. Read the upstream feature document this command implements.
2. Read the corresponding user stories and acceptance criteria.
3. Verify the command's scope is consistent with the feature's stated scope boundaries.

**When writing or editing command files:**

- Write as **direct instructions to Claude** — imperative, second-person ("Search for...", "Open a proof session on...").
- Do not include frontmatter, metadata, or document headers beyond a brief one-line description of the command.
- Specify **which tools to use** at each step. Available tool families:
  - Search MCP tools: `search_by_name`, `search_by_type`, `search_by_structure`, `search_by_symbols`, `get_lemma`, `find_related`, `list_modules`
  - Proof MCP tools: `open_proof_session`, `close_proof_session`, `list_proof_sessions`, `observe_proof_state`, `get_proof_state_at_step`, `extract_proof_trace`, `submit_tactic`, `step_backward`, `step_forward`, `get_proof_premises`, `get_step_premises`
  - Vernacular MCP tool: `vernacular_query` (covers Print, Check, About, Locate, Search, Compute, Eval)
  - Visualization MCP tools: `visualize_proof_state`, `visualize_proof_tree`, `visualize_dependencies`, `visualize_proof_sequence`
  - Standard Claude Code tools: Read, Write, Edit, Grep, Glob, Bash
- Structure as **numbered steps** for the primary workflow.
- Include **decision points** — when to branch, retry, or fall back to alternative strategies.
- Include an **edge cases** section covering empty input, missing prerequisites, and large-scale operation.
- Specify the **output format** — what the user sees when the command completes.
- Always instruct Claude to **clean up resources** (close proof sessions, etc.) before finishing.
- Do not re-state what or why — only how. Reference the feature document for rationale.
- Do not include motivational text, background context, or prose that does not directly instruct Claude's behavior.

**Naming convention:** The filename (minus `.md`) is the slash command name. `/proof-repair` → `proof-repair.md`.

**One per:** slash command
