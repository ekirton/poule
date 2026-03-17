# Test Feedback Guidelines

Inherits from [claude/feedback-standards.md](../../claude/feedback-standards.md).

## Authority

Authority chain: `specification/` → `doc/architecture/` → `doc/architecture/data-models/`. Before filing, read the test's corresponding specification — an apparent test issue may be a spec problem (file spec feedback instead).

## Location Format

`test/feedback/<name>.md` — name matches source without `test_` prefix (e.g., `test_storage.py` → `storage.md`).

## Severity Definitions

- **high:** test cannot pass with correct implementation, or produces false passes.
- **medium:** test is fragile or underspecified.
- **low:** clarity or coverage gap.

## Resolving

- **Test is wrong:** fix the test to match the spec.
- **Spec is wrong:** file feedback in `specification/feedback/` per `specification/feedback/CLAUDE.md`.
- **Architecture is wrong:** file feedback in `doc/architecture/feedback/` per `doc/architecture/feedback/CLAUDE.md`.
