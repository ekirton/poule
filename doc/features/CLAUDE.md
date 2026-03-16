## Feature Documents

**Layer:** 2 — Behavioral Specification

**Location:** `doc/features/<feature-name>.md`

**Authority:** Feature documents are **derived from** PRDs (`doc/requirements/`) and user stories (`doc/requirements/stories/`). They are authoritative for downstream architecture documents (`doc/architecture/`) on **what** a feature does and **why**. Architecture documents describe **how**.

**Before writing or editing feature documents:**

1. Read the upstream PRD and user stories this feature traces to.
2. Verify the feature scope is consistent with the PRD's requirements and priority levels.

**When writing or editing feature documents:**

- Describe the feature from the **user's perspective** — what it does, why it exists, and the design decisions and tradeoffs behind it.
- Capture intent and rationale. Do **not** describe pipelines, data formats, or implementation mechanics — those belong in the corresponding architecture document.
- State what the feature provides and what it explicitly does **not** provide.
- Reference upstream PRDs and user stories that this feature addresses.

**One per:** feature or concern
