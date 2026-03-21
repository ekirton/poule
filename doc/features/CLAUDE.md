## Feature Documents

**Layer:** 2 — Behavioral Specification

**Location:** `doc/features/<feature-name>.md`

**Authority:** Feature documents are **derived from** PRDs (`doc/requirements/`). They are authoritative for downstream architecture documents (`doc/architecture/`) on **what** a feature does and **why**. Architecture documents describe **how**.

**Before writing or editing feature documents:**

1. Read the upstream PRD this feature traces to.
2. Verify the feature scope is consistent with the PRD's requirements and priority levels.

**When writing or editing feature documents:**

- Describe the feature from the **user's perspective** — what it does, why it exists, and the design decisions and tradeoffs behind it.
- Capture intent and rationale. Do **not** describe pipelines, data formats, or implementation mechanics — those belong in the corresponding architecture document.
- State what the feature provides and what it explicitly does **not** provide.
- Reference the upstream PRD that this feature addresses.
- Include an **Acceptance Criteria** section with testable GIVEN/WHEN/THEN entries that trace to PRD requirement IDs (e.g., "Traces to: RC-P0-1"). Use concrete values, not placeholders.

**Priority levels:** P0 = must-have, P1 = should-have, P2 = nice-to-have, P3 = future consideration

**Stability indicators:** Stable = unlikely to change, Draft = details may evolve, Volatile = expected to change

**One per:** feature or concern
