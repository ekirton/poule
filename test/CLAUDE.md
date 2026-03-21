# Test Writing Guidelines

## Source of Authority

Tests are derived from specification documents (`specification/`). The specification is authoritative for all behavioral expectations, formulas, contracts, and edge cases. When writing a test, consult the relevant specification — not intuition or general expectations about how a function "should" behave.

Authority chain: `specification/*.md` → `doc/architecture/` → `doc/architecture/data-models/`

For test writing standards (formula-derived bounds, mock discipline, contract tests), see the `writing-tests` skill.
