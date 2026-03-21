---
name: sdd
description: Run the Spec-Driven Development pipeline for a feature or change. Walks through SDD stages in order with enforced layer boundaries and feedback loops. Use when asked to build a feature end-to-end, propagate a change, fix a bug through SDD, or follow the SDD process. Accepts an optional starting layer as the first argument (e.g., "/sdd specification fix the caching bug").
disable-model-invocation: true
argument-hint: "[starting-layer] <description>"
---

# Spec-Driven Development Pipeline

Execute the SDD pipeline for: $ARGUMENTS

## Determine the starting stage

Parse the first word of the arguments. If it matches a layer name, start at that stage and skip earlier stages. Otherwise, start at Stage 1.

| First word | Start at |
|-----------|----------|
| `requirements` | Stage 1 |
| `features` | Stage 2 |
| `architecture` | Stage 3 |
| `specification` | Stage 4 |
| `tests` | Stage 5 |
| `implementation` | Stage 5 |
| *(anything else)* | Stage 1 (full pipeline) |

Note: `implementation` maps to Stage 5 (tests first), enforcing TDD. To skip tests entirely, use the `/implementation` phase command directly instead of `/sdd`.

Work through the stages below **starting from the determined stage**. At each stage, set the phase to enforce layer boundaries. Do not invent requirements or infer unnecessary details — ask the user when ambiguities exist.

## Autonomy rules

**Human-in-the-loop layers** (`doc/requirements/`, `doc/features/`, `doc/architecture/`):
- **Propagating downward** from the stage above (e.g., requirements→features, features→architecture): proceed autonomously.
- **Originating changes** (writing initial content, fixing a gap found during triage, or making changes NOT derived from the stage immediately above): present 2-3 options with critical analysis and a recommendation. Wait for the user to approve before editing.

**Autonomous layers** (`specification/`, `test/`, `src/`):
- Proceed without human intervention.
- **After 3 feedback cycles, stop and present the situation to the user.** This prevents infinite loops. Summarize what was attempted, what keeps failing, and ask for direction.

## Stage 1: Requirements

1. Run: `echo "requirements" > .claude/sdd-layer`
2. If propagating from a user request that clearly defines the requirements, write or update the PRD in `doc/requirements/` autonomously.
3. If the requirements already exist and are sufficient, confirm with the user and skip to Stage 2.
4. If the change requires judgment (e.g., scope decisions, priority trade-offs), present options with analysis and a recommendation. Wait for approval.

## Stage 2: Features

1. Run: `echo "features" > .claude/sdd-layer`
2. If propagating from Stage 1, propagate to `doc/features/` autonomously.
3. If this is the starting stage, or if the change requires judgment beyond what the requirements prescribe, present options with analysis and a recommendation. Wait for approval.
4. If a problem with the requirements is detected, do **not** edit requirements — surface the issue to the user and **stop**.

## Stage 3: Architecture

1. Run: `echo "architecture" > .claude/sdd-layer`
2. Read `doc/architecture/data-models/expression-tree.md` and `doc/architecture/data-models/index-entities.md`.
3. If propagating from Stage 2, propagate to `doc/architecture/` autonomously.
4. If this is the starting stage, or if the change involves design decisions not prescribed by the feature doc, present options with analysis and a recommendation. Wait for approval.
5. If a problem is found in upstream documents, do **not** edit them — surface the issue to the user and **stop**.

## Stage 4: Specifications

1. Run: `echo "specification" > .claude/sdd-layer`
2. Read the parent architecture document.
3. Propagate architecture down to `specification/`.
4. If a problem is identified with the architecture, write a detailed description to `doc/architecture/feedback/` and **stop**. Notify the user — architecture changes require human approval.
5. Record the blast radius — write changed spec filenames to `.claude/sdd-blast-radius`:
   `echo "specification/channels.md specification/storage.md" > .claude/sdd-blast-radius`

## Stage 5: Tests and Implementation

This stage follows TDD: write failing tests first, then implement until tests pass. Track feedback cycles (any return to step 1 or 3 from a feedback resolution counts as one cycle).

1. Read the blast radius from `.claude/sdd-blast-radius` if it exists.
2. Run: `echo "tests" > .claude/sdd-layer`
3. Write or update tests for the new/changed specifications within the blast radius.
4. Do **not** change specifications. If a spec problem is found, go to step 9.
5. Run `python -m pytest test/ -x -q`. New tests covering the change should fail. Existing tests may pass or fail.
6. Run: `echo "implementation" > .claude/sdd-layer`
7. Write the implementation to make tests pass. Do **not** change tests or specifications.
8. Run `python -m pytest test/ -x -q` after each significant change. When all tests pass, proceed to Completion.
9. **If a spec problem is found** (during tests or implementation):
   - Run: `echo "specification" > .claude/sdd-layer`
   - Fix the specification. Delete the feedback file.
   - Increment feedback cycle count. Return to step 2.
10. **If a test problem is found** (during implementation):
    - Run: `echo "tests" > .claude/sdd-layer`
    - Fix the test. Delete the feedback file.
    - Increment feedback cycle count. Return to step 6.
11. **If an architecture problem is found:**
    - Write to `doc/architecture/feedback/`, notify the user, and **stop**.
12. **After 3 feedback cycles**, stop and present the situation to the user: summarize what was attempted, what keeps failing, and ask for direction.

## Completion

1. Run: `echo "free" > .claude/sdd-layer`
2. Remove `.claude/sdd-blast-radius` if it exists.
3. Check off completed tasks in `tasks/` (update `- [ ]` to `- [x]`).
4. If any feedback files still exist, notify the user and **stop**.
5. Report what was done and which files were changed.
6. Do **not** make a PR — the user decides when the branch is ready.
