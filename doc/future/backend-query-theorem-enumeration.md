# Proposal: Backend Query Theorem Enumeration

## Status

Future proposal — not scheduled for implementation.

## Problem

The extraction campaign enumerates theorems in two ways:

1. **Regex scan** (current): Parses `.v` source files with a regex matching `Theorem|Lemma|Proposition|Corollary|Fact`. Fast but incomplete — misses `Instance`, `Definition`, `Example`, `Remark`, `Let`, `Program`, `Fixpoint`, and `CoFixpoint` declarations that have proof bodies. Also produces false positives from comments and ambiguous short names.

2. **Index query** (planned): Queries the `declarations` table in `index.db` for all entries with `kind IN ('lemma', 'theorem', 'instance', 'definition')`. Reliable for FQN and kind, but cannot distinguish definitions with proof bodies (`Definition foo : T. Proof. ... Qed.`) from direct definitions (`Definition foo := expr.`), requiring a try-and-skip strategy.

Neither approach queries the Coq kernel itself. A backend query would be the authoritative source of what is provable.

## Proposed Approach

Replace or augment theorem enumeration with queries to the running Coq backend (coq-lsp via Petanque, or coqtop):

### Method A: `Search` command enumeration

For each loaded `.v` file, execute:
```
Search _ inside ModuleName.
```
This returns all declarations defined within the module. Filter by those that have proof bodies by attempting `Print Proof <name>` — declarations without proof bodies return an error.

### Method B: Document symbol enumeration via LSP

coq-lsp implements the LSP `textDocument/documentSymbol` request, which returns a structured list of all symbols in a file with their kinds (theorem, definition, etc.) and ranges. This is a single request per file and provides:
- Symbol name and kind
- Source range (line/column)
- Nesting information (proofs inside sections/modules)

### Method C: Vernac AST inspection

coq-lsp can return the parsed Vernac AST for a document. Inspecting the AST directly would identify all proof-bearing commands (`VernacTheorem`, `VernacDefinition` with proof body, `VernacInstance`, etc.) with zero ambiguity.

## Advantages Over Index Query

- **Authoritative**: The backend knows exactly which declarations have proof bodies — no try-and-skip needed.
- **No index dependency**: Works without a pre-built index.db, simplifying the extraction pipeline for first-time users.
- **Handles section-local names**: `Let` declarations inside sections are visible to the backend but may not appear in the index (they are section-local and do not survive `End Section`).
- **Version-consistent**: The backend reads the same `.vo` files it will replay, eliminating staleness risk.

## Why Deferred

The index-based approach (querying `index.db`) covers ~95% of the gap with zero additional backend calls:
- It captures `Instance`, `Definition`, `Example`, `Remark` declarations that the regex misses.
- The try-and-skip strategy for non-proof definitions is fast (~50ms per failed attempt) and has no false negatives.
- The index is always available in the standard extraction workflow (`poule extract` requires a built index).

Backend queries add per-file latency (loading each file, executing queries), increase backend process lifetime and memory pressure, and add a dependency on coq-lsp's LSP compliance for `documentSymbol` or Vernac AST requests. These are worth the cost only if the try-and-skip rate is unacceptably high (>20% of attempted definitions have no proof body), which empirical measurement should determine first.

## Prerequisites

- Empirical data on the try-and-skip rate from index-based enumeration
- coq-lsp `documentSymbol` or Vernac AST support verified for current Coq version
- Performance benchmarking: per-file backend query latency vs. index query latency

## Relationship to Other Work

- Depends on: extraction campaign infrastructure (`campaign.py`)
- Supersedes: regex-based enumeration (but regex remains as a zero-dependency fallback)
- Complements: index-based enumeration (could run as a validation pass to check index completeness)
