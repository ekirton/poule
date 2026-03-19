# Test Writing Guidelines

## Source of Authority

Tests are derived from specification documents (`specification/`). The specification is authoritative for all behavioral expectations, formulas, contracts, and edge cases. When writing a test, consult the relevant specification — not intuition or general expectations about how a function "should" behave.

Authority chain: `specification/*.md` → `doc/architecture/` → `doc/architecture/data-models/`

## Upstream Authority Is Immutable

Specification documents (`specification/`), architecture documents (`doc/architecture/`), and data model documents (`doc/architecture/data-models/`) **must not be modified** when writing tests. Tests encode the specification contracts using TDD — they are derived from the spec, not the other way around.

- If a specification appears ambiguous or incorrect, file feedback in `specification/feedback/` — do not change the spec. Follow the feedback standards defined in `specification/feedback/CLAUDE.md`.
- If an architecture or data model document conflicts with a specification, file feedback in `doc/architecture/feedback/`. Follow the feedback standards defined in `doc/architecture/feedback/CLAUDE.md`.
- If a test cannot be written to match the spec, the issue belongs in feedback, not in a spec edit.

## Numeric Bounds Must Be Formula-Derived

When a specification defines a formula, all test bounds and expected values **must be computed from that formula** — never estimated by intuition.

- **Compute the expected value** by substituting the test input into the spec formula before choosing an assertion bound.
- **Show the derivation** in a comment next to the assertion so reviewers can verify it.
- **Do not use "round number" bounds** (e.g., `< 1.01`) unless the formula confirms they hold at the chosen input.

Example — wrong:
```python
# "Should be very close to 1.0 for large freq"
assert symbol_weight(1_000_000) < 1.01  # intuition, not derived
```

Example — correct:
```python
# 1.0 + 2.0 / log2(1_000_001) ≈ 1.1003
assert symbol_weight(1_000_000) < 1.2
```

## Tests Must Fail to Reveal, Not Pass to Reassure

A test that cannot fail is worthless. Every assertion must be capable of catching a real deficiency in the implementation. A passing test should mean the implementation satisfies the spec — not that the test avoided checking.

- **No vacuous assertions.** `assert isinstance(result, list)` followed by `if result: assert ...` verifies nothing when the implementation returns `[]` due to a bug. If the spec says the list should be populated, assert `len(result) > 0`.
- **No conditional verification.** If a contract requires fields to be populated, assert they are populated unconditionally. A test that only checks field values "if they exist" will pass when the implementation silently returns empty data.
- **Prefer a failing test over a passing one.** When an implementation bug causes a test to pass for the wrong reason (e.g., empty output triggers the correct error path by accident), rewrite the test so it fails until the bug is fixed. A red test that points at the real problem is more valuable than a green test that hides it.
- **Contract tests must exercise the real interface.** A contract test that gets no data from the real backend (due to a transport bug, timeout, etc.) and passes anyway is not a contract test — it is dead code with a green checkmark.

## Mock Discipline

Every `Mock()` or `patch()` requires a corresponding **contract test** that exercises the real implementation against the same interface. Skipping via pytest marker (e.g., `@pytest.mark.requires_coq`) is acceptable when external tools are needed; omitting the test is not.

```python
# Good: consumer test mocks the backend
def test_pipeline_calls_backend():
    backend = Mock()
    backend.list_declarations.return_value = [("A", "Lemma", {})]
    ...

# Good: contract test verifies real backend satisfies the same interface
@pytest.mark.requires_coq
def test_coq_lsp_backend_list_declarations():
    backend = CoqLspBackend(...)
    decls = backend.list_declarations(Path("test_fixture.vo"))
    assert isinstance(decls, list)
    assert all(len(d) == 3 for d in decls)

# Bad: consumer test exists but no contract test for the real implementation
```

Before declaring a task phase complete, verify every `Mock()`/`patch()` has a corresponding contract test. If not, the phase is incomplete.

### Mock Return Values Must Use Real Types

Mock `return_value` must use the actual type the real implementation returns (e.g., dataclass, not `dict`). This exercises serialization and attribute-access paths in the consumer.

## Test File Feedback

When a test appears to conflict with its specification, file feedback in `test/feedback/<test-file-name>.md` describing the discrepancy. Do not silently adjust the test or the implementation. Follow the feedback standards defined in `test/feedback/CLAUDE.md`.
