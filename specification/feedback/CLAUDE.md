# Specification Feedback Guidelines

Inherits from [claude/feedback-standards.md](../../claude/feedback-standards.md).

## Authority

Authority chain: `doc/architecture/data-models/` → `doc/architecture/` → `specification/`. Before filing, read the spec's parent architecture document and relevant data model documents.

## Location Format

`specification/feedback/<spec-name>.md` — name matches source (e.g., `storage.md` → `storage.md`).

## Severity Definitions

- **high:** blocks implementation or causes incorrect behavior.
- **medium:** forces an implementer judgment call the spec should have made.
- **low:** documentation clarity, edge case coverage, or future-proofing.

## Resolving

- **Spec is wrong:** fix the specification to match the upstream authority.
- **Architecture is wrong:** file feedback in `doc/architecture/feedback/` per `doc/architecture/feedback/CLAUDE.md`.
