# Specification Feedback: MePo Symbol-Relevance Channel

**Source:** [specification/channel-mepo.md](../channel-mepo.md)
**Date:** 2026-03-16
**Reviewer:** Implementation pass (code generation)

---

## Issue 1: Test bound for symbol_weight at freq=1,000,000 is inconsistent with the specified formula

**Severity:** high
**Section:** 4.1 Symbol Weight Function

**Problem:** The specification defines `symbol_weight(freq) = 1.0 + 2.0 / log2(freq + 1)`. The test `test_large_freq_approaches_1` asserts `symbol_weight(1_000_000) < 1.01`. However, `1.0 + 2.0 / log2(1_000_001) = 1.0 + 2.0 / 19.93 ≈ 1.1003`, which is greater than 1.01. The formula is confirmed correct by two other tests: `test_freq_1_returns_3` (checks `== 3.0`) and `test_freq_1000_approximately_1_2` (checks `== approx(1.0 + 2.0 / log2(1001))`). The upper bound `< 1.01` in the third test is mathematically incompatible with the formula.

**Impact:** The test `test_large_freq_approaches_1` cannot pass with the specified formula. One of 42 tests fails. The implementation is correct per the spec and the other two `symbol_weight` tests.

**Suggested resolution:** Change the test assertion from `assert w < 1.01` to `assert w < 1.2` (or `assert w < 1.15`), which is consistent with `1.0 + 2.0 / log2(1_000_001) ≈ 1.1003`. Alternatively, if a steeper decay was intended, revise the formula in the spec and all three tests to match.
