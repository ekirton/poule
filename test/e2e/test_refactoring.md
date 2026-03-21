# Refactoring and Proof Engineering

**Assess refactoring blast radius:**
```
If I change add_comm in examples/arith.v, what breaks? Show me the full impact analysis
```

**Compress a verbose proof:**
```
/compress-proof rev_involutive in examples/lists.v
```

**Lint proof scripts for issues:**
```
/proof-lint examples/lint_targets.v
```

**Scan for incomplete proofs:**
```
/proof-obligations examples/
```

**Migrate deprecated names:**
```
/migrate-rocq
```
