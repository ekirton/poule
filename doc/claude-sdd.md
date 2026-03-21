# Spec-Driven Development with Claude Code

This guide explains how to use Claude Code with the project's Spec-Driven Development (SDD) workflow. SDD enforces a chain of authority across documentation layers so that requirements flow downward through features, architecture, specifications, tests, and implementation — and each layer is protected from unauthorized modification by layers below it.

## The SDD Layers

| Layer | Directory | What belongs here |
|-------|-----------|-------------------|
| 1. Requirements | `doc/requirements/` | Business goals, user needs, constraints (PRDs) |
| 2. Features | `doc/features/` | What the system does and why, acceptance criteria |
| 3. Architecture | `doc/architecture/` | How it works at design level, data models |
| 4. Specifications | `specification/` | Implementable contracts (Design by Contract) |
| 5. Tasks | `tasks/` | Detailed implementation breakdown |
| 6. Tests | `test/` | Test suite derived from specifications |
| 7. Implementation | `src/`, `commands/` | Code, slash command prompts |

Each layer is **derived from** the one above and **authoritative for** the one below. The core discipline: while working at one layer, do not edit layers above it.

## Commands

| Command | Purpose |
|---------|---------|
| `/diagnose` | Investigate a bug: find root cause, triage, auto-fix if autonomous layers |
| `/triage` | Read-only audit: trace a known root cause up the authority chain |
| `/sdd` | Run the SDD pipeline from a given layer downward (TDD: tests before implementation) |

### Phase commands

Each phase restricts which directories Claude can edit:

| Command | Editable directories | Blocked from |
|---------|---------------------|-------------|
| `/requirements` | `doc/requirements/` | everything else |
| `/features` | `doc/features/` | everything else |
| `/architecture` | `doc/architecture/` | everything else |
| `/specification` | `specification/` | everything else |
| `/tasks` | `tasks/` | everything else |
| `/tests` | `test/` | everything else |
| `/implementation` | `src/`, `commands/`, `tasks/` | `test/`, `specification/`, `doc/` |
| `/free` | anything | nothing blocked |

**Default phase is `free`** — no restrictions. Enter a phase when you want discipline enforced.

## How Enforcement Works

Enforcement uses four mechanisms — none of which consume context tokens:

**PreToolUse hook** (`.claude/hooks/layer-guard.sh`) — Runs before every `Edit` or `Write` operation. Reads the current phase from `.claude/sdd-layer`, checks whether the target file is in an allowed directory, and blocks the operation (exit code 2) with a descriptive error message if not.

**PostToolUse hook** (`.claude/hooks/post-edit.sh`) — Runs after every `Edit` or `Write` operation. During `implementation` or `free` phases, automatically runs `pytest` if the edited file is under `src/` or `test/`. Skipped during other phases to avoid noise when tests are expected to fail.

**PostCompact hook** (`.claude/hooks/post-compact.sh`) — After context compaction, re-injects the current SDD phase so Claude doesn't forget which layer it's working in.

**Phase state file** (`.claude/sdd-layer`) — Single-line file containing the current phase name. Written by commands, read by hooks. Gitignored.

## The Feedback Mechanism

When Claude encounters a problem in an upstream layer, it must not edit that layer directly. Instead, it writes a feedback file:

| Working in | Problem found in | Write feedback to |
|-----------|-----------------|------------------|
| `specification/` | `doc/architecture/` | `doc/architecture/feedback/` |
| `test/` | `specification/` | `specification/feedback/` |
| `src/` | `test/` | `test/feedback/` |
| `src/` | `specification/` | `specification/feedback/` |

In **autonomous layers** (specification, tests, implementation), Claude resolves feedback itself — fixing the spec or test, deleting the feedback file, and continuing. It only stops and notifies you when:
- The problem requires changes to a **doc/ layer** (architecture, features, requirements)
- **3 feedback cycles** have been reached without resolution

## TDD: Tests Before Implementation

The `/sdd` pipeline follows Test-Driven Development: write a failing test first, then implement until it passes. This applies to both new features and bug fixes:

- `/sdd specification "..."` → writes spec → writes failing tests → implements → tests pass
- `/sdd tests "..."` → writes failing test for the bug → implements → tests pass
- `/sdd implementation "..."` → redirects to tests first (same as `/sdd tests`)

To skip tests entirely (e.g., for a trivial fix you've already verified), use the `/implementation` phase command directly instead of `/sdd`.

## Blast Radius Tracking

When Claude modifies specifications (Stage 4), it records which spec files changed to `.claude/sdd-blast-radius`. This ensures the test-writing stage knows which tests to update, even if context compaction occurs between stages. The file is cleaned up at completion.

## Autonomy Rules

| Layer | Autonomy | When human approval is needed |
|-------|----------|-------------------------------|
| `doc/requirements/` | Human-in-the-loop | Always, unless propagating from a clear user request |
| `doc/features/` | Human-in-the-loop | When originating changes; autonomous when propagating from requirements |
| `doc/architecture/` | Human-in-the-loop | When originating changes or making design decisions; autonomous when propagating from features |
| `specification/` | Fully autonomous | Never — Claude proceeds without asking |
| `test/` | Fully autonomous | Never |
| `src/` | Fully autonomous | Never |

**Originating vs. propagating:** If Claude is flowing downward through the pipeline (requirements→features→architecture), it propagates autonomously. If Claude needs to change a doc/ layer for other reasons (fixing a gap, making a design decision not prescribed by the layer above), it presents options with analysis and waits for approval.

**Feedback loop cap:** After 3 feedback cycles, Claude stops and asks for direction rather than looping indefinitely.

## Writing Guideline Skills

Detailed writing standards are available as on-demand skills (not loaded every session):

| Skill | Covers |
|-------|--------|
| `/writing-specs` | Document structure, EARS template, Design by Contract, state machines |
| `/writing-tests` | Formula-derived bounds, mock discipline, contract tests |
| `/writing-tasks` | Task structure template, completion rules |
| `/writing-architecture` | Architecture doc format, component boundaries, data models |

## Full Pipeline: `/sdd`

Build a feature end-to-end:

```
/sdd "add caching to the retrieval pipeline"
```

Start from a specific layer:

```
/sdd specification "fix MePo zero-frequency handling"   → starts at specifications
/sdd tests "reproduce the off-by-one bug"               → starts at tests (TDD)
```

The pipeline flows: requirements → features → architecture → specifications → tests (failing) → implementation → tests (passing) → completion.

## Bug Fix Workflow

### Step 1: Diagnose with `/diagnose`

Pass the bug report directly. Claude investigates (using a subagent to keep context clean), triages, and **acts on the result**:

```
You:  /diagnose "MePo symbol_weight raises KeyError for zero-frequency symbols"

      → Claude investigates (subagent reads src/, test/, spec)
      → Triage: all doc/ layers OK, spec has a gap
      → Auto-fix: invokes /sdd specification "add zero-frequency edge case"
      → Claude fixes spec, writes failing test, fixes implementation, tests pass
      → Done
```

When the fix requires doc/ changes, Claude stops and asks:

```
You:  /diagnose "impact_analysis returns 0 edges for stdlib lemmas"

      → Triage: architecture has a GAP (no reverse edge storage)
      → Claude presents options with critical analysis
      → Waits for your approval before proceeding
```

Use `/triage` instead if you already know the root cause — it skips investigation and goes straight to the authority chain audit (runs in an isolated context, read-only).

### Step 2: Handle the result

If `/diagnose` auto-fixed the bug (autonomous layers), you're done.

If `/diagnose` stopped for approval (doc/ layers), choose an option. Claude proceeds with `/sdd` from the appropriate layer:

```
You:    Option 1 — add reverse edge table.
        → Claude runs /sdd architecture "add reverse dependency edge storage"
        → Proceeds autonomously through spec, tests, implementation
```

### Step 3: Handle feedback loops

`/sdd` resolves feedback loops automatically within autonomous layers. It only stops when:

- A doc/ layer needs changes (requires your approval)
- 3 feedback cycles have been reached (asks for direction)
- All feedback files are exhausted and tests pass (done)

### Quick reference

| Situation | What to say |
|-----------|-------------|
| You have a bug report | `/diagnose "bug description"` |
| Claude found a root cause, wants to execute a plan | `/triage "description"` |
| `/diagnose` stopped for approval on doc/ changes | Choose an option; Claude proceeds |
| New feature, full pipeline | `/sdd "feature description"` |
| You want to work without restrictions | `/free` |
| Claude wrote feedback and stopped | Review, then: `/sdd <upstream-layer> "fix"` |
