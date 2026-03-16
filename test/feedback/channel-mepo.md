# Test Feedback: channel-mepo

## test_large_freq_approaches_1

**Test**: `TestSymbolWeight::test_large_freq_approaches_1`
**File**: `test/test_channel_mepo.py`

**Issue**: The test asserts `symbol_weight(1_000_000) < 1.01`, but the spec formula `1.0 + 2.0 / log2(freq + 1)` yields approximately `1.1003` for `freq = 1,000,000`:

```
1.0 + 2.0 / log2(1_000_001) ≈ 1.0 + 2.0 / 19.93 ≈ 1.1003
```

The `< 1.01` bound is too tight. A correct bound would be `< 1.2` or the test should check against the exact formula value `≈ 1.1003`.

The other two `symbol_weight` tests pass and confirm the formula is implemented correctly:
- `symbol_weight(1) == 3.0` ✓
- `symbol_weight(1000) ≈ 1.0 + 2.0 / log2(1001)` ✓
