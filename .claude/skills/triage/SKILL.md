---
name: triage
description: Trace a known root cause up the SDD authority chain to determine which layer the fix should start at. Use when Claude has already identified a root cause and you need to determine the blast radius. Runs in an isolated context.
context: fork
agent: general-purpose
model: opus
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash
argument-hint: "<root cause description>"
---

Triage a bug or failing test to determine which SDD layer the fix should start at: $ARGUMENTS

You have identified (or been given) a root cause. Before making any changes, trace it upward through the authority chain to find the highest layer that needs correction. Do NOT edit any files — this is a read-only audit.

Steps:

1. Summarize the root cause in one sentence.

2. Identify which implementation file(s) contain the bug. Read the relevant source in src/ and the corresponding test(s) in test/.

3. Find the specification that governs this behavior. Read it in specification/. Ask:
   - Does the spec correctly describe the expected behavior?
   - Is the bug a deviation from the spec, or does the spec itself have a gap or error?

4. If the spec appears wrong or incomplete, read the parent architecture document in doc/architecture/. Ask:
   - Does the architecture correctly describe the design?
   - Did the spec misinterpret the architecture, or is the architecture itself flawed?

5. If the architecture appears wrong, read the feature document in doc/features/. Ask:
   - Does the feature doc correctly capture what the system should do?
   - Is the architecture inconsistent with the feature intent?

6. If the feature doc appears wrong, read the PRD in doc/requirements/. Ask:
   - Is the requirement clearly stated?
   - Did the feature doc misinterpret the requirement?

7. Stop at the highest layer where a problem is found. Report your findings as a table:

   | Layer | Document | Status | Finding |
   |-------|----------|--------|---------|
   | Requirements | doc/requirements/X.md | OK / GAP / ERROR | brief note |
   | Features | doc/features/X.md | OK / GAP / ERROR | brief note |
   | Architecture | doc/architecture/X.md | OK / GAP / ERROR | brief note |
   | Specification | specification/X.md | OK / GAP / ERROR | brief note |
   | Tests | test/X.py | OK / GAP / ERROR | brief note |
   | Implementation | src/poule/X.py | OK / GAP / ERROR | brief note |

8. Recommend which phase command to start with (e.g., "/specification", "/implementation") and briefly describe the fix at each affected layer, working top-down.

IMPORTANT: Do not make any edits. Only read files and report findings.
