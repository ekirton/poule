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

## Phase 3: Decide and act

7. Determine the highest affected layer from the triage. Do NOT present a report table yet — act first, report at the end.

   **If the fix requires changes to `doc/` layers** (requirements, features, or architecture):
   - These require human approval. Present the triage table (same format as step 29), then present 2-3 options with critical analysis and a recommendation. Wait for the user to decide before proceeding. Stop here.

   **If the fix starts at `specification/` or below** (all doc/ layers are OK):
   - This is within autonomous scope. Do not wait for user approval. Proceed directly to Phase 4.

## Phase 4: Fix the specification (if needed)

Skip this phase if the specification is correct (the bug is purely an implementation deviation). Go directly to Phase 5.

8. Run: `echo "specification" > $CLAUDE_PROJECT_DIR/sdd-layer`
9. Read the parent architecture document.
10. Fix the specification gap or error in `specification/`.
11. If a problem is identified with the architecture while fixing the spec, write a detailed description to `doc/architecture/feedback/` and **stop**. Notify the user — architecture changes require human approval.
12. Record the blast radius — write changed spec filenames to `$CLAUDE_PROJECT_DIR/sdd-blast-radius`:
    `echo "specification/channels.md specification/storage.md" > $CLAUDE_PROJECT_DIR/sdd-blast-radius`

## Phase 5: Tests and implementation (TDD)

Write failing tests first, then implement until tests pass. Track feedback cycles (any return to an earlier step from a feedback resolution counts as one cycle).

13. Read the blast radius from `$CLAUDE_PROJECT_DIR/sdd-blast-radius` if it exists.
14. Run: `echo "tests" > $CLAUDE_PROJECT_DIR/sdd-layer`
15. Write or update tests that reproduce the bug or cover the spec change within the blast radius.
16. Do **not** change specifications. If a spec problem is found, go to step 21.
17. Run `python -m pytest test/ -x -q`. New tests covering the change should fail. Existing tests may pass or fail.
18. Run: `echo "implementation" > $CLAUDE_PROJECT_DIR/sdd-layer`
19. Write the implementation to make tests pass. Do **not** change tests or specifications.
20. Run `python -m pytest test/ -x -q` after each significant change. When all tests pass, proceed to Phase 6.
21. **If a spec problem is found** (during tests or implementation):
    - Run: `echo "specification" > $CLAUDE_PROJECT_DIR/sdd-layer`
    - Fix the specification. Delete the feedback file.
    - Increment feedback cycle count. Return to step 14.
22. **If a test problem is found** (during implementation):
    - Run: `echo "tests" > $CLAUDE_PROJECT_DIR/sdd-layer`
    - Fix the test. Delete the feedback file.
    - Increment feedback cycle count. Return to step 18.
23. **If an architecture problem is found:**
    - Write to `doc/architecture/feedback/`, notify the user, and **stop**.
24. **After 3 feedback cycles**, stop and present the situation to the user: summarize what was attempted, what keeps failing, and ask for direction.

## Phase 6: Completion

25. Run: `echo "free" > $CLAUDE_PROJECT_DIR/sdd-layer`
26. Remove `$CLAUDE_PROJECT_DIR/sdd-blast-radius` if it exists.
27. Check off completed tasks in `tasks/` (update `- [ ]` to `- [x]`).
28. If any feedback files still exist, notify the user and **stop**.
29. Present the triage table:

**Root cause:** <2-3 sentence summary with specific file:line references>

| Layer | Document | Status | Finding |
|-------|----------|--------|---------|
| Requirements | doc/requirements/X.md | OK / GAP / ERROR | brief note |
| Features | doc/features/X.md | OK / GAP / ERROR | brief note |
| Architecture | doc/architecture/X.md | OK / GAP / ERROR | brief note |
| Specification | specification/X.md | OK / GAP / ERROR | brief note |
| Tests | test/X.py | OK / GAP / ERROR | brief note |
| Implementation | src/poule/X.py | OK / GAP / ERROR | brief note |

30. Report what was done and which files were changed.
31. Do **not** make a PR — the user decides when the branch is ready.
