# Module and Library Browsing

End-to-end tests for the `/browse` skill — module exploration, typeclass browsing, dependency traversal, and cycle detection.

**No arguments — top-level overview:**
```
Browse the available Coq libraries — what's installed?
```

**Browse a specific module prefix:**
```
Browse Coq.Arith — what submodules and key declarations are available?
```

**Browse a third-party library module:**
```
Browse mathcomp.algebra.ssralg — what's in it?
```

**List all typeclasses:**
```
Open a proof session on add_comm in examples/arith.v, then browse typeclasses — what typeclasses are registered?
```

**List instances of a typeclass:**
```
Browse instances of Decidable — what types have decidable equality?
```

**Dependency traversal — transitive closure:**
```
Browse deps Nat.add_comm — what does it transitively depend on?
```

**Dependency traversal — with depth limit:**
```
Browse deps Nat.add_comm --depth 1 — show only direct dependencies
```

**Dependency traversal — with scope filter:**
```
Browse deps Nat.add_comm --scope Coq.Arith — only show dependencies within Coq.Arith
```

**Impact analysis — what depends on a declaration:**
```
Browse impact Nat.add_0_r — what is the blast radius if I change it?
```

**Cycle detection:**
```
Browse cycles — are there any circular dependencies in the project?
```

**Error handling — unknown module prefix:**
```
Browse Nonexistent.Module.Xyz — what happens?
```

**Error handling — typeclass not found:**
```
Browse instances of NonexistentTypeclass — what error do I get?
```

**Interactive navigation — drill deeper:**
```
Browse Coq.Arith, then drill into Coq.Arith.PeanoNat — show me the key lemmas
```
