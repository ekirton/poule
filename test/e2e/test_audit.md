# Axiom Auditing

End-to-end tests for the `/audit` skill — single-theorem, module-wide, and comparison audits of axiom dependencies.

**Single theorem — axiom-free:**
```
Audit the axiom dependencies of ring_morph in examples/algebra.v
```

**Single theorem — with axioms:**
```
Audit add_0_r_v1 in examples/algebra.v — what axioms does it depend on, and are any of them classical?
```

**Module-wide audit:**
```
Audit all theorems in examples/algebra.v for axiom dependencies — how many are axiom-free?
```

**Module-wide audit with flag filtering:**
```
Audit examples/algebra.v and flag any theorems that use classical or choice axioms
```

**Constructive shorthand flag:**
```
Audit examples/algebra.v --constructive — which theorems block extraction to constructive code?
```

**Comparison audit — shared and unique axioms:**
```
Compare the axiom profiles of add_0_r_v1, add_0_r_v2, and add_0_r_v3 in examples/algebra.v — which has the weakest assumptions?
```

**Comparison audit — mixed constructivity:**
```
Compare the axiom dependencies of ring_morph and zmul_expand in examples/algebra.v — is one more constructive than the other?
```

**Single theorem — implications and suggestions:**
```
Audit Nat.add_comm — is it constructive? Can it be extracted to OCaml?
```

**Error handling — theorem not found:**
```
Audit nonexistent_theorem_xyz in examples/algebra.v
```

**Large module — summary not exhaustive list:**
```
Audit the Coq.Arith.PeanoNat module — give me a summary, not a listing of every theorem
```
