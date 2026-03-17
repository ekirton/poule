# Implementation Feedback Guidelines

Inherits from [claude/feedback-standards.md](../../claude/feedback-standards.md).

## Authority

Authority chain: `specification/` → `doc/architecture/` → `doc/architecture/data-models/`. Tests (`test/`) encode specification contracts. Before filing, read the implementation's corresponding specification and test file.

## Location Format

`src/feedback/<module-path>.md` — name matches source module with path separators as hyphens (e.g., `channels/mepo.py` → `channels-mepo.md`).

## Severity Definitions

- **high:** test fails or contract violated.
- **medium:** implementation works but diverges from spec intent.
- **low:** code quality, performance, or clarity.

## Resolving

- **Implementation is wrong:** fix the code. Run tests to verify.
- **Test is wrong:** file feedback in `test/feedback/` per `test/feedback/CLAUDE.md`.
- **Spec is wrong:** file feedback in `specification/feedback/` per `specification/feedback/CLAUDE.md`.
