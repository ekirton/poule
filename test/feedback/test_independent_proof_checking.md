---
name: test_independent_proof_checking pytest.warns(None) API removal
description: pytest.warns(None) was removed in pytest 8; test crashes on this env
type: feedback
severity: low
---

## Issue

`TestResolveLibraryName::test_no_matching_load_path_returns_bare_name` uses
`pytest.warns(None)` which was deprecated in pytest 7 and removed in pytest 8:

```python
with pytest.warns(None) as _:
    pass
```

In the current pytest version (≥ 8), this raises:
```
TypeError: exceptions must be derived from Warning, not <class 'NoneType'>
```

The test never reaches the actual assertion (`result == "Scratch"`).

## Root Cause

`pytest.warns(None)` was used to assert that no warnings were emitted.
It was removed in pytest 8.0. The block is around `pass` anyway (not around
the actual function call), so it was not checking warnings on the code under
test.

## Suggested Resolution

Replace the `with pytest.warns(None) as _: pass` block with either:
- Nothing (remove it, since it was wrapping `pass`)
- `with warnings.catch_warnings(): ...` if warnings actually need to be checked

The implementation of `resolve_library_name` is correct and returns `"Scratch"`
for a non-matching load path. Only the test scaffolding is broken.

Filed by: TDD implementation agent (2026-03-17)
