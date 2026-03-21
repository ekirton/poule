# Code Extraction Management

Managed extraction of verified Coq/Rocq definitions to executable OCaml, Haskell, or Scheme. Claude Code invokes extraction as a tool to bridge the gap between formally verified specifications and runnable programs — handling target language selection, dependency resolution, failure diagnosis, and output preview so the user never has to write raw extraction commands or decipher opaque error messages.

---

## Problem

Extraction is the only path from a verified Coq proof to code that actually runs. A theorem proven correct in Coq has no practical deployment value until its computational content is extracted to a general-purpose language. Yet extraction is where verified software projects most often stall.

The errors are common and opaque. An axiom missing a realizer, an opaque term that blocks reduction, a universe inconsistency deep in a dependency chain, an unsupported match pattern, a module type mismatch — each produces a terse Coq error that assumes the user already understands extraction internals. Learners abandon extraction attempts entirely. Experienced users resort to trial-and-error, toggling transparency flags and extraction directives until something compiles, with no confidence that the resulting code is what they intended.

Even when extraction succeeds, the workflow is clumsy. Users write extraction commands by hand, wait for output, inspect it manually, and repeat if the target language or options were wrong. There is no way to preview what extraction will produce before committing it to a file, no guidance on which target language suits a given definition, and no explanation of why a particular extraction looks the way it does.

## Solution

Claude Code manages the full extraction workflow through a single tool interface. The user names a definition and a target language; the tool handles the rest.

### Single Definition Extraction

Extracting a single named definition produces the corresponding code in the target language and returns it directly. If the definition does not exist in the current environment, the tool reports the unknown name. The extracted code is returned as-is — one definition, one output, no side effects.

### Recursive Extraction

When a definition depends on other definitions, recursive extraction pulls in the entire transitive dependency tree and returns a self-contained module. The user gets everything needed to compile the extracted code independently in the target language, without manually tracking which helpers, types, and sub-definitions are required. If the definition has no dependencies beyond Coq's built-in types, recursive extraction produces the same output as single extraction.

### Target Language Selection

Every extraction request specifies a target language: OCaml, Haskell, or Scheme. These are the three languages Coq's extraction mechanism supports. If a user requests an unsupported language, the tool responds with the list of supported options rather than failing silently. The choice of language is per-request — the user can extract the same definition to multiple languages in sequence to compare results.

### Failure Explanation

When extraction fails, the tool returns both the raw Coq error and a plain-language explanation of what went wrong, along with at least one suggested fix. The five most common failure categories are covered: opaque terms that need transparency directives, axioms that lack realizers and need `Extract Constant` bindings, universe inconsistencies that require restructuring, unsupported match patterns, and module type mismatches. The user sees what broke, why it broke, and what to try next — without needing to consult the Coq reference manual.

### Preview Before Write

Extraction never writes to disk by default. Every extraction request returns the generated code in the tool response so the user can review it first. If the output looks correct, the user can then request that it be written to a specified file path. If something is wrong — the target language was a poor fit, an extraction option needs adjustment, the output is unexpectedly large — the user iterates without any file having been created. This preview-then-commit workflow prevents the common mistake of overwriting a file with extraction output that turns out to be incorrect.

## Design Rationale

### Why extraction is essential for verified software

A Coq proof is a mathematical artifact. It establishes that a property holds for all inputs, that an algorithm meets its specification, that a protocol preserves an invariant. But a Coq proof does not run. Extraction is what turns the computational content of a proof into a program that executes — an OCaml function, a Haskell module, a Scheme procedure. Without extraction, formal verification is an academic exercise disconnected from production software. Every verified software project that ships real code depends on extraction working correctly.

### Relationship to assumption auditing

Extraction quality is directly tied to the logical health of the definitions being extracted. A definition that depends on axioms without realizers will either fail to extract or produce code with holes — `assert false` stubs where the axiom's computational content should be. This is where extraction management connects to assumption auditing: axiom-free proofs extract cleanly, while axiom-dependent proofs require explicit realizer bindings. By surfacing axiom warnings during extraction, the tool closes the loop between proof hygiene and code generation — users discover at extraction time, not at runtime, that their verified code rests on unimplemented assumptions.

---

## Acceptance Criteria

### Extract a Single Definition

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq environment with a defined term `my_function` WHEN I request extraction of `my_function` to OCaml THEN the tool returns valid OCaml code corresponding to that definition
- GIVEN a Coq environment with a defined term `my_function` WHEN I request extraction to Haskell THEN the tool returns valid Haskell code corresponding to that definition
- GIVEN a Coq environment with a defined term `my_function` WHEN I request extraction to Scheme THEN the tool returns valid Scheme code corresponding to that definition
- GIVEN a definition name that does not exist in the current environment WHEN I request extraction THEN the tool returns an error identifying the unknown name

**Traces to:** R-CE-P0-1, R-CE-P0-3

### Recursive Extraction

**Priority:** P0
**Stability:** Stable

- GIVEN a definition `serialize` that depends on `encode` and `to_bytes` WHEN I request recursive extraction of `serialize` to OCaml THEN the tool returns extracted code for `serialize`, `encode`, and `to_bytes`
- GIVEN a recursive extraction request WHEN the result is returned THEN all transitive dependencies are included in the output
- GIVEN a definition with no dependencies beyond Coq's built-in types WHEN I request recursive extraction THEN the output contains only the extracted definition itself

**Traces to:** R-CE-P0-2, R-CE-P0-3

### Choose Target Language

**Priority:** P0
**Stability:** Stable

- GIVEN a valid extraction request WHEN I specify OCaml as the target THEN the tool produces OCaml syntax
- GIVEN a valid extraction request WHEN I specify Haskell as the target THEN the tool produces Haskell syntax
- GIVEN a valid extraction request WHEN I specify Scheme as the target THEN the tool produces Scheme syntax
- GIVEN a valid extraction request WHEN I specify an unsupported language (e.g., Python) THEN the tool returns an error listing the supported languages

**Traces to:** R-CE-P0-3

### Explain Extraction Failures

**Priority:** P0
**Stability:** Stable

- GIVEN a definition that references an opaque term WHEN extraction fails THEN the tool explains that the term is opaque and suggests using `Transparent` or providing an extraction directive
- GIVEN a definition that depends on an axiom without a realizer WHEN extraction fails THEN the tool identifies the axiom and suggests providing an `Extract Constant` directive
- GIVEN a definition with a universe inconsistency during extraction WHEN extraction fails THEN the tool explains the universe issue and suggests potential restructurings
- GIVEN any extraction failure WHEN the error is returned THEN the response includes both the raw Coq error and a plain-language explanation with at least one suggested fix

**Traces to:** R-CE-P0-4

### Preview Extracted Code Before Writing

**Priority:** P0
**Stability:** Stable

- GIVEN a successful extraction request WHEN the result is returned THEN the extracted code is displayed in the response and no file is written to disk
- GIVEN a previewed extraction WHEN I am satisfied with the output THEN I can request the tool to write the code to a specified file path
- GIVEN a previewed extraction WHEN I am not satisfied THEN I can request extraction again with different options without any file having been created

**Traces to:** R-CE-P0-5, R-CE-P1-2
