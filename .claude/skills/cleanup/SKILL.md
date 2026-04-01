---
name: cleanup
description: Find and remove dead code, orphaned tests, and unused modules left behind after spec changes, feature removals, or pivots. Walks the SDD layers top-down to identify code that no longer has upstream justification. Use after a pivot, feature removal, or when you suspect dead code exists.
disable-model-invocation: true
argument-hint: "[scope hint — e.g., 'neural retrieval removal' or 'all']"
---

# Dead Code Cleanup

Find and remove code that has lost its upstream justification: $ARGUMENTS

## Phase 1: Identify removed or narrowed specifications

1. Launch an Explore agent to scan for orphaned code:
   - "Search for functions, classes, modules, and test files in `src/` and `test/` that are no longer referenced by any current specification in `specification/` or architecture document in `doc/architecture/`. Also check for: (a) imports of deleted modules, (b) CLI commands or entry points that reference removed features, (c) scripts in `scripts/` that serve removed features. The user's scope hint is: $ARGUMENTS. Return a structured list grouped by category: dead modules, dead functions, dead tests, dead scripts, orphaned imports."

2. When the agent returns, compile the candidate list. For each candidate, record:
   - File path and function/class name
   - Why it appears orphaned (which spec was removed or narrowed)

## Phase 2: Verify candidates

Not everything without a spec reference is dead — utilities, shared helpers, and infrastructure code may be used transitively.

3. For each candidate module or function, check for live callers:
   - Grep for imports and call sites across `src/`, `test/`, `scripts/`, and `commands/`.
   - If a candidate has live callers outside the dead-code set, remove it from the list.
   - If a candidate's only callers are themselves candidates, keep both on the list (the whole cluster is dead).

4. Group the verified candidates into removal sets — clusters of files that can be removed together without breaking anything.

## Phase 3: Present findings

5. Present the removal plan to the user as a table:

| # | Category | File | Symbol | Reason |
|---|----------|------|--------|--------|
| 1 | dead module | src/Poule/neural/channel.py | — | spec `neural-retrieval.md` removed |
| 2 | dead test | test/unit/test_neural_retrieval.py | — | tests removed module |
| 3 | orphaned import | src/Poule/cli/commands.py | `import channel` | imports dead module |
| ... | | | | |

6. Ask the user to confirm which removals to proceed with. Wait for approval before editing. Do **not** remove anything the user excludes.

## Phase 4: Remove dead code

7. Run: `echo "implementation" > $CLAUDE_PROJECT_DIR/sdd-layer`
8. For each approved removal set:
   - Delete dead modules and test files entirely.
   - Remove orphaned imports, registrations, and references from live files.
   - Remove dead functions/classes from files that contain both live and dead code.
   - Remove entries from `__init__.py` exports, CLI command registrations, and script references.
9. Run `python -m pytest test/ -x -q` after each removal set. If a test fails:
   - The candidate was not actually dead. Revert the removal and remove it from the list.
   - Report the false positive to the user.

## Phase 5: Completion

10. Run: `echo "free" > $CLAUDE_PROJECT_DIR/sdd-layer`
11. Present a summary:

**Removed:**
| # | File | Action |
|---|------|--------|
| 1 | src/Poule/neural/channel.py | deleted |
| 2 | src/Poule/cli/commands.py | removed import of `channel` |
| ... | | |

**Kept (false positives):**
| # | File | Reason kept |
|---|------|-------------|
| ... | | |

12. Do **not** make a PR — the user decides when the branch is ready.
