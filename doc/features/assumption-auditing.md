# Assumption Auditing

Every Coq theorem rests on axioms, but which axioms — and whether they are acceptable — is rarely obvious from the proof script alone. Assumption auditing gives Claude Code the ability to inspect what a theorem actually depends on, classify each axiom by kind, and surface plain-language explanations so developers can make informed decisions about their proof foundations without leaving the conversational workflow.

---

## Problem

Coq's `Print Assumptions` command (see [Coq reference manual, Displaying Assumptions](https://coq.inria.fr/doc/V8.20.0/refman/proof-engine/vernacular-commands.html#coq:cmd.Print-Assumptions)) reports the axioms and opaque dependencies of a named identifier. It is the only built-in mechanism for answering the question "what does this theorem actually assume?" — and it works. But three factors make it insufficient for developers who rely on Claude Code as a proof assistant:

1. **Axiom dependencies are invisible by default.** Nothing in the proof script or type signature reveals that a theorem transitively depends on the law of excluded middle, functional extensionality, or a user-declared axiom. Developers discover this only if they think to run `Print Assumptions` manually, and many do not — especially when the dependency is inherited from an upstream library rather than introduced directly.

2. **Raw output demands manual interpretation.** `Print Assumptions` returns a flat list of identifiers and their types. It does not say whether `Classical_Prop.classic` is a classical logic axiom or what its presence means for code extraction. A developer must already know the Coq axiom landscape to interpret the output, which defeats the purpose for anyone who is not already an expert.

3. **Single-theorem granularity does not scale.** Library maintainers who need to enforce an axiom policy across an entire module — "no classical logic," "no choice axioms" — must run `Print Assumptions` on every theorem individually and collate the results by hand. There is no batch mode and no comparison facility.

The consequence is that unintended axioms silently accumulate. A constructive development that accidentally pulls in the law of excluded middle loses its computational content and cannot be extracted to executable code. Two libraries that adopt incompatible axiom sets cannot be composed. These problems are preventable, but only if axiom auditing is fast, automatic, and interpretable.

## Solution

An MCP tool that Claude Code invokes to inspect the axiom foundations of Coq theorems. The user asks a question — "what does this theorem assume?" or "is my module fully constructive?" — and Claude calls the auditing tool, interprets the structured result, and explains the findings in plain language.

### Single-Theorem Auditing

The core interaction: given a fully qualified theorem name, the tool reports every axiom and opaque dependency the theorem rests on. When a theorem has no axiom dependencies beyond Coq's core logic, the tool reports it as closed — a useful positive signal that the theorem is self-contained. When axioms are present, each one is returned with its type and its classification.

### Axiom Classification

Every reported axiom is assigned to a recognized category:

- **Classical logic** — axioms that introduce the law of excluded middle, double-negation elimination, or equivalent principles (e.g., `Classical_Prop.classic`). Their presence means the proof is not constructive and may not yield executable code through extraction.
- **Extensionality** — axioms asserting that functions or propositions with the same behavior are equal (e.g., `functional_extensionality_dep`, `propositional_extensionality`). Generally safe for extraction but may block definitional reduction.
- **Choice** — axioms providing the ability to extract witnesses from existence proofs (e.g., `Coq.Logic.ChoiceFacts` variants, indefinite description). These have strong logical consequences and interact with both classical and constructive settings.
- **Proof irrelevance** — axioms asserting that all proofs of a proposition are equal. Useful for quotient constructions but incompatible with some type-theoretic developments.
- **Custom/user-defined** — any axiom not in the standard library. These require the most scrutiny because their consistency is the developer's responsibility.

Each classified axiom is accompanied by a short explanation of what it asserts and what its presence implies for the development — whether it affects extractability, constructivity, or compatibility with other axiom sets.

### Batch Auditing

For library maintainers, the tool audits every theorem in a given module in a single invocation. The result is a summary: which axioms appear across the module, how many theorems depend on each axiom, and which theorems are axiom-free. When a module is intended to be constructive, any theorem that depends on classical, choice, or proof-irrelevance axioms is explicitly flagged so that accidental dependencies surface immediately rather than at release time.

### Comparison Between Theorems

When a developer has multiple formulations of the same result — or is choosing between alternative library lemmas — the tool compares their assumption profiles side by side. The comparison shows axioms unique to each theorem, axioms shared by all, and a clear indication of which formulation carries the weakest assumptions. For three or more theorems, the result is a matrix showing axiom usage across all candidates.

---

## Design Rationale

### Why classification matters

A flat list of axiom names is not actionable for most developers. The name `functional_extensionality_dep` does not self-evidently communicate that it is an extensionality axiom that is generally safe for extraction, just as `classic` does not explain that it collapses the distinction between provable and true and blocks computational extraction. Classification turns a list of names into a risk assessment: classical axioms are a red flag in constructive developments, choice axioms have known consistency concerns in certain settings, and custom axioms demand manual review. Without classification, the tool would be no more useful than `Print Assumptions` itself.

### Why batch auditing

Axiom discipline is a module-level concern, not a theorem-level one. A library that advertises itself as constructive must be constructive throughout — a single theorem with a classical dependency compromises the claim. Checking theorems one at a time is tedious and error-prone; developers skip it, and unintended dependencies accumulate. Batch auditing makes the module-level question answerable in a single step, which means it actually gets asked.

### Relationship to code extraction

The primary consumer of axiom-free proofs is Coq's extraction mechanism, which translates Coq terms to OCaml, Haskell, or Scheme. Extraction produces correct code only when the extracted terms are computationally meaningful — classical axioms, which assert the existence of objects without constructing them, produce opaque stubs that fail at runtime. Assumption auditing is, in practice, a prerequisite for reliable extraction: before extracting a module, developers need to know which theorems are safe to extract and which carry axioms that will produce non-functional code. The classification categories are chosen to align with the distinctions that matter for extraction.

---

## Acceptance Criteria

### Single-Theorem Assumption Auditing

**Priority:** P0
**Stability:** Stable

- GIVEN a compiled Coq library containing theorem `T` WHEN assumption auditing is invoked for `T` THEN it returns the complete list of axioms and opaque dependencies that `T` relies on
- GIVEN a theorem with no axiom dependencies beyond Coq's core WHEN assumption auditing is invoked THEN it reports that the theorem is closed (axiom-free)
- GIVEN a theorem that depends on `Classical_Prop.classic` WHEN assumption auditing is invoked THEN `Classic` appears in the results with its type

**Traces to:** R-P0-1, R-P0-2, R-P0-6

### Classify Axiom Types

**Priority:** P0
**Stability:** Stable

- GIVEN a theorem that depends on `Coq.Logic.FunctionalExtensionality.functional_extensionality_dep` WHEN assumption auditing is invoked THEN the axiom is classified under the "extensionality" category
- GIVEN a theorem that depends on `Classical_Prop.classic` WHEN assumption auditing is invoked THEN the axiom is classified under the "classical logic" category
- GIVEN a theorem that depends on a user-defined axiom not in the standard library WHEN assumption auditing is invoked THEN the axiom is classified as "custom/user-defined"
- GIVEN any classified axiom WHEN the result is inspected THEN it includes a short plain-language explanation of what the axiom asserts and its common implications

**Traces to:** R-P0-3, R-P0-4

### Assumption Auditing MCP Tool

**Priority:** P0
**Stability:** Stable

- GIVEN a running MCP server WHEN its tool list is inspected THEN an assumption auditing tool is present with a documented schema
- GIVEN the assumption auditing MCP tool WHEN it is invoked with a fully qualified theorem name THEN it returns the classified assumption list
- GIVEN the assumption auditing MCP tool WHEN it is invoked with an identifier that does not exist in the loaded environment THEN it returns a clear error message

**Traces to:** R-P0-5

### Batch Audit of a Module

**Priority:** P1
**Stability:** Stable

- GIVEN a compiled Coq module `M` containing 50 theorems WHEN batch auditing is invoked for `M` THEN it returns the assumption list for every theorem in the module
- GIVEN a batch audit result WHEN it is inspected THEN it includes a summary showing which axioms appear, how many theorems depend on each axiom, and which theorems are axiom-free
- GIVEN a module with up to 200 theorems WHEN batch auditing is invoked THEN it completes within 30 seconds

**Traces to:** R-P1-1, R-P1-5

### Detect Unintended Axiom Use

**Priority:** P1
**Stability:** Stable

- GIVEN a module where all theorems are intended to be constructive WHEN batch auditing is invoked THEN any theorem depending on classical logic, choice, or proof irrelevance axioms is explicitly flagged
- GIVEN a flagged theorem WHEN the flag is inspected THEN it identifies the specific axiom and the category that triggered the flag
- GIVEN a module where no theorem uses classical axioms WHEN batch auditing is invoked THEN the summary confirms that the module is fully constructive

**Traces to:** R-P1-2

### Compare Assumption Profiles Between Theorems

**Priority:** P1
**Stability:** Stable

- GIVEN two theorems `A` and `B` WHEN assumption comparison is invoked THEN it returns the axioms unique to `A`, the axioms unique to `B`, and the axioms shared by both
- GIVEN three or more theorems WHEN assumption comparison is invoked THEN it returns a matrix showing which axioms each theorem depends on
- GIVEN two theorems where one has strictly fewer axiom dependencies than the other WHEN comparison is invoked THEN the result clearly indicates which theorem has the weaker assumption set

**Traces to:** R-P1-3, R-P1-5

### Audit from Pre-Built Index

**Priority:** P1
**Stability:** Draft

- GIVEN a compiled `.vo` file for a Coq library WHEN assumption auditing is invoked for a theorem in that library THEN it returns results without requiring an active `coqtop` session, if the necessary information is available in the compiled files
- GIVEN a library that has been indexed by the semantic lemma search infrastructure WHEN assumption auditing is invoked THEN it leverages the existing index to resolve identifiers
- GIVEN a theorem whose assumptions cannot be determined from compiled files alone WHEN assumption auditing is invoked THEN it falls back to a live Coq session or returns a clear message explaining the limitation

**Traces to:** R-P1-4
