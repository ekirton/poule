---
name: test_code_extraction_management bytes_written spec inconsistency
description: Spec example says bytes_written=20 for a 19-byte string
type: feedback
severity: medium
---

## Issue

`TestWriteExtraction::test_writes_code_to_file` and `test_spec_example_write`
assert:
```python
result.bytes_written == 20
f.read() == "let add x y = x + y"   # 19 characters
```

These two assertions are contradictory: `"let add x y = x + y"` is 19 bytes in
UTF-8/ASCII. If `bytes_written == 20`, the file must contain a trailing `\n`,
but then `f.read()` would return `"let add x y = x + y\n"` (20 chars), not
matching the 19-char assertion.

## Root Cause

The spec example (§9) likely has an off-by-one error — the string has 19
characters but is documented as 20 bytes.

## Suggested Resolution

Either:
1. Change the expected string in the test to `"let add x y = x + y\n"` (20
   bytes, with trailing newline), OR
2. Change `bytes_written` expectation from 20 to 19 to match the actual
   string length

The implementation currently writes the code as-is (19 bytes), matching the
file content assertion but failing the `bytes_written == 20` assertion.

Filed by: TDD implementation agent (2026-03-17)
