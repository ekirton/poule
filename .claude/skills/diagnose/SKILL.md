---
name: diagnose
description: Investigate a bug report — find root cause, trace it up the SDD authority chain, and auto-fix if the problem is within autonomous layers (specification and below). Use when given a bug description, error report, or failing test.
disable-model-invocation: true
argument-hint: "<bug description>"
---

Diagnose a bug and triage it to the correct SDD layer: $ARGUMENTS

## Phase 1: Find the root cause

Delegate the investigation to an Explore subagent to keep the main context clean.

1. Launch an Explore agent with this prompt:
   - The bug description from the user
   - "Search the codebase for the relevant code paths. Trace the call chain to find where the behavior diverges. Check handlers, validation, tests. Return: the root cause (file, function, line, why), and which source/test/spec files are involved."

2. When the agent returns, summarize the root cause in 2-3 sentences with specific file:line references.

## Phase 2: Triage up the authority chain

Read each layer's documents to find the highest layer that needs correction. Only read the specific documents relevant to the bug — do not read broadly.

3. Read the specification that governs this behavior (in `specification/`). Ask:
   - Does the spec correctly describe the expected behavior?
   - Is the bug a deviation from the spec, or does the spec itself have a gap?

4. If the spec appears wrong or incomplete, read the parent architecture document (in `doc/architecture/`). Ask:
   - Does the architecture correctly describe the design?
   - Did the spec misinterpret the architecture, or is the architecture flawed?

5. If the architecture appears wrong, read the feature document (in `doc/features/`). Ask:
   - Does the feature doc correctly capture what the system should do?

6. If the feature doc appears wrong, read the PRD (in `doc/requirements/`). Ask:
   - Is the requirement clearly stated?

## Phase 3: Report and decide

7. Present findings:

**Root cause:** <2-3 sentence summary with specific file:line references>

| Layer | Document | Status | Finding |
|-------|----------|--------|---------|
| Requirements | doc/requirements/X.md | OK / GAP / ERROR | brief note |
| Features | doc/features/X.md | OK / GAP / ERROR | brief note |
| Architecture | doc/architecture/X.md | OK / GAP / ERROR | brief note |
| Specification | specification/X.md | OK / GAP / ERROR | brief note |
| Tests | test/X.py | OK / GAP / ERROR | brief note |
| Implementation | src/poule/X.py | OK / GAP / ERROR | brief note |

## Phase 4: Act on the result

8. Determine the highest affected layer:

   **If the fix starts at `specification/` or below** (all doc/ layers are OK):
   - This is within autonomous scope. Determine the starting layer and invoke `/sdd` to execute the fix. Do not wait for user approval.
   - **TDD rule:** When the fix is purely an implementation bug (spec is correct, implementation diverges), start at `tests` — not `implementation`. Write a failing test that reproduces the bug first, then fix the implementation until it passes. Invoke `/sdd tests "<fix description>"`.
   - When the spec itself has a gap, start at `specification`. The `/sdd` pipeline will then flow through tests before implementation.

   **If the fix requires changes to `doc/` layers** (requirements, features, or architecture):
   - These require human approval. Present 2-3 options with critical analysis and a recommendation. Wait for the user to decide before proceeding.
