# Architecture Feedback Guidelines

Inherits from [claude/feedback-standards.md](../../../claude/feedback-standards.md).

## Authority

Authority chain: `doc/architecture/data-models/` → `doc/architecture/` → `doc/requirements/`, `doc/features/`. Before filing, read the relevant data model documents and related architecture documents.

## Location Format

`doc/architecture/feedback/<doc-name>.md` — name matches source (e.g., `retrieval-pipeline.md` → `retrieval-pipeline.md`).

## Severity Definitions

- **high:** blocks specification or causes contradictions across multiple specs.
- **medium:** forces a spec writer judgment call the architecture should have made.
- **low:** documentation clarity or future-proofing.

## Resolving

- **Architecture is wrong:** fix to match the data model or requirements.
- **Data model is wrong:** fix the data model if you own it, otherwise escalate.
- **Requirements are wrong:** do not change. Escalate to stakeholder.
