## Task Breakdown Documents

**Layer:** 4 — Implementation Specification

**Location:** `tasks/<feature-or-story>.md`

**Authority:** Task breakdowns are **derived from** specification documents (`specification/`) which are derived from architecture documents (`doc/architecture/`). Specifications are the direct authority for task content; architecture documents and data models are the indirect authority.

**Before generating task breakdowns:**

1. Read the specification document being decomposed.
2. Read its parent architecture document (linked at the top of the spec).
3. Read `doc/architecture/data-models/expression-tree.md` and `doc/architecture/data-models/index-entities.md` — these are authoritative for all entity names, node labels, field types, and constraints. All names in tasks must match the data model documents exactly.
4. Read cross-referenced specification documents to verify interface contracts match.
5. If a specification contradicts a data model or architecture document, file feedback in `specification/feedback/` rather than silently adopting the incorrect name. Follow the feedback standards defined in `specification/feedback/CLAUDE.md`.
6. If an architecture or data model document appears ambiguous or contradictory, file feedback in `doc/architecture/feedback/`. Follow the feedback standards defined in `doc/architecture/feedback/CLAUDE.md`.

**Upstream authority is immutable.** Specification documents (`specification/`), architecture documents (`doc/architecture/`), and data model documents (`doc/architecture/data-models/`) must not be modified when writing task breakdowns.

**When generating task breakdowns:**

- Decompose from architecture documents — not from feature documents or PRDs directly.
- Scope each task to a single implementable unit (file, module, or function).
- Trace every task to a specific requirement or acceptance criterion.
- Record any decomposition decisions you made **beyond** what the Layer 3 spec prescribed — surface these to the architect.
- Tasks are disposable LLM artifacts. They are regenerated when upstream specs change.

**Task structure:**
```
- [ ] **Task name** — Brief description
  - **Traces to:** [story or requirement reference]
  - **Depends on:** [prior task references, if any]
  - **Produces:** [files or modules]
  - **Done when:** [completion criteria]
```

**One per:** feature or cohesive implementation unit

**Marking tasks complete:**

- When a task is implemented, update its checkbox from `- [ ]` to `- [x]`.
- When **all** tasks in a file are complete, delete the file entirely.
