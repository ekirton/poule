---
name: diagnose
description: Investigate a bug report — find root cause, trace it up the SDD authority chain, recommend which layer to fix. Use when given a bug description, error report, or failing test. Runs in an isolated context to preserve the main conversation for the fix.
context: fork
agent: general-purpose
model: opus
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
argument-hint: "<bug description>"
---

Diagnose a bug and triage it to the correct SDD layer: $ARGUMENTS

This is a read-only investigation. Do NOT edit any files.

## Phase 1: Find the root cause

1. Parse the bug description. Identify the failing behavior, affected tool/function, and any error messages or symptoms mentioned.

2. Search the codebase for the relevant code paths:
   - Use Grep/Glob to find the function, tool handler, or module mentioned in the bug.
   - Read the implementation. Trace the code path that produces the incorrect behavior.
   - If MCP tools are involved, check the handler in `src/poule/server/handlers.py` and the validation in `src/poule/server/validation.py`.
   - Follow the call chain until you find where the behavior diverges from what's expected.

3. Read the relevant test files to understand what is and isn't covered.

4. Summarize the root cause in 2-3 sentences. Be specific: name the file, function, and line where the bug originates. Explain WHY the current code produces the wrong result.

## Phase 2: Triage up the authority chain

Now trace the root cause upward through the SDD layers to find the highest layer that needs correction.

5. Read the specification that governs this behavior (in `specification/`). Ask:
   - Does the spec correctly describe the expected behavior?
   - Is the bug a deviation from the spec, or does the spec itself have a gap?

6. If the spec appears wrong or incomplete, read the parent architecture document (in `doc/architecture/`). Ask:
   - Does the architecture correctly describe the design?
   - Did the spec misinterpret the architecture, or is the architecture flawed?

7. If the architecture appears wrong, read the feature document (in `doc/features/`). Ask:
   - Does the feature doc correctly capture what the system should do?

8. If the feature doc appears wrong, read the PRD (in `doc/requirements/`). Ask:
   - Is the requirement clearly stated?

## Phase 3: Report

9. Present findings in this format:

**Root cause:** <2-3 sentence summary with specific file:line references>

| Layer | Document | Status | Finding |
|-------|----------|--------|---------|
| Requirements | doc/requirements/X.md | OK / GAP / ERROR | brief note |
| Features | doc/features/X.md | OK / GAP / ERROR | brief note |
| Architecture | doc/architecture/X.md | OK / GAP / ERROR | brief note |
| Specification | specification/X.md | OK / GAP / ERROR | brief note |
| Tests | test/X.py | OK / GAP / ERROR | brief note |
| Implementation | src/poule/X.py | OK / GAP / ERROR | brief note |

**Recommendation:** `/sdd <starting-layer> "<fix description>"`

IMPORTANT: Do not make any edits. Only read files and report findings.
