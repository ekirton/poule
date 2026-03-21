# Type Error Explanation

Coq type errors are notoriously opaque. They report expected and actual types in fully expanded form, often spanning dozens of lines, with no indication of where the types diverge, what coercions were attempted, or what the user likely intended. Resolving a type error today requires manually running `Check`, `Print`, `About`, and `Print Coercions` to reconstruct the context the error message omits — a process that demands expert knowledge of Coq's type system. Type Error Explanation provides an `/explain-error` slash command that automates this entire diagnostic workflow: it parses the error, inspects the relevant types and coercions in the user's environment, and delivers a plain-language explanation of what went wrong and how to fix it.

---

## Problem

When a Coq user encounters a type error, the error message itself is rarely sufficient to understand or resolve the problem. Coq prints the expected type and the actual type, but for types involving nested inductive families, universe polymorphism, implicit arguments, or coercions, these printouts are walls of text with no highlighting of where the divergence occurs. The user must then embark on a manual investigation: run `Print` to see what a type alias expands to, run `About` to check how many arguments a function expects, query `Print Coercions` to find out why an expected coercion was not applied, and mentally diff two large type expressions to locate the mismatch. Newcomers rarely know which commands to run. Experienced users know but spend significant time on what is ultimately mechanical detective work.

No existing tool addresses this gap. CoqIDE, VsCoq, and Proof General display Coq's raw error messages without interpretation. No IDE inspects the relevant type definitions, analyzes coercion paths, or explains the error in plain language. The diagnosis of a type error is an inherently multi-step, contextual reasoning task — exactly the kind of task that benefits from an agentic workflow combining structured inspection with natural language explanation.

## Solution

The `/explain-error` slash command gives users a single action that replaces the entire manual diagnostic workflow. When a user encounters a type error and invokes `/explain-error`, the command orchestrates multiple MCP tools to parse the error, inspect the types involved, analyze relevant coercions, and produce a complete diagnostic in plain language.

### Plain-Language Explanation

The core of every diagnostic is an explanation that a user can actually read. Rather than presenting raw type expressions for the user to decode, the command identifies what went wrong — which argument has the wrong type, where two types diverge, why a unification failed — and states it in terms the user can understand. Technical terms like "inductive type" or "universe" are defined when they cannot be avoided. The explanation pinpoints the specific sub-expression where types diverge rather than asking the user to visually diff two large type expressions.

### Contextual Type Inspection

The error message alone rarely tells the whole story. The command fetches the definitions of the types involved — expanding aliases, revealing parameters, and showing the actual structure behind opaque names. When the expected and actual types have the same name but come from different modules, the command identifies the ambiguity. When implicit arguments were inferred to unexpected types, the command shows what was inferred and why it conflicts with the rest of the term.

### Coercion and Scope Analysis

Many type errors arise not from genuinely wrong types but from coercions that were not applied or notations interpreted in the wrong scope. The command inspects available coercion paths between the expected and actual types, explains whether a coercion exists and why Coq did not apply it, and identifies when a notation like `+` or `::` was interpreted in a scope different from what the user intended. These are the errors that frustrate users most because the code "looks right" — the explanation reveals the hidden mismatch.

### Fix Suggestions

Understanding what went wrong is only half the problem; users also need to know what to do about it. The command suggests concrete fixes: explicit type annotations, coercion declarations, `@`-notation to override implicit arguments, `%scope` annotations to select the right notation scope, or alternative definitions that would make the term well-typed. When no clear fix can be determined, the command says so rather than producing a misleading suggestion.

## Scope

Type Error Explanation provides:

- A single `/explain-error` slash command that completes the full diagnostic workflow in one invocation
- Parsing of Coq type error messages to extract structured information (expected type, actual type, location, environment)
- Contextual inspection of type definitions, coercion paths, implicit arguments, and notation scopes
- Plain-language explanation of the root cause, accessible to users who do not fluently read Coq type expressions
- Concrete fix suggestions for common type error patterns
- Diagnosis of universe inconsistency errors and canonical structure projection failures for advanced users

Type Error Explanation does not provide:

- Modifications to Coq's error reporting or type checker
- New MCP tools — it consumes tools built by other initiatives (vernacular introspection, universe inspection, notation inspection)
- IDE plugins — the slash command runs within Claude Code
- Automated error correction — fixes are suggested, not applied without user approval
- Diagnosis of non-type errors such as tactic failures or syntax errors

---

## Design Rationale

### Why a slash command rather than automatic invocation

Type error diagnosis requires orchestrating multiple inspection steps and reasoning about the combined results — a workflow that benefits from being explicitly triggered rather than running on every error. Not every type error needs a detailed explanation; experienced users often recognize the problem at a glance. Making the diagnosis opt-in via `/explain-error` keeps the interaction lightweight when the user does not need help while providing deep analysis when they do.

### Why combine error parsing with contextual inspection

Coq's error messages are incomplete by design: they report the type mismatch but not the definitions behind the types, the coercion landscape, or the implicit argument decisions that led to the mismatch. Parsing the error alone would produce a reformatted version of the same opaque message. The value comes from combining the error with contextual inspection — fetching type definitions, checking coercion paths, examining implicit argument inference — to produce an explanation that contains information the error message itself does not. This is why no static tool has solved the problem: it requires multi-step, context-dependent reasoning.

### Why suggest fixes rather than apply them

Type errors often have multiple valid resolutions, and the best choice depends on the user's intent — something the tool cannot always determine. Applying a fix automatically risks "resolving" the type error in a way that changes the meaning of the user's code. Suggesting fixes preserves user agency: the user sees the options, understands the tradeoffs through the accompanying explanation, and chooses the resolution that matches their intent.

### Why build on existing MCP tools rather than new ones

The inspection capabilities this feature needs — querying type definitions, checking coercions, examining universe constraints, inspecting notations — are general-purpose operations that other features also require. Building them as standalone MCP tools in separate initiatives (vernacular introspection, universe inspection, notation inspection) and consuming them here avoids duplication, keeps the tool count manageable, and ensures that improvements to the underlying inspection tools automatically benefit type error diagnosis.

## Acceptance Criteria

### Error Parsing and Type Inspection

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq type error of the form "The term X has type T1 while it is expected to have type T2" WHEN `/explain-error` is invoked THEN it correctly extracts the term, the actual type, and the expected type as separate structured fields
- GIVEN a type error that includes an environment context ("In environment ...") WHEN the error is parsed THEN the local variable bindings from the environment are extracted and available for subsequent inspection
- GIVEN a type error that spans multiple lines due to complex types WHEN the error is parsed THEN the full types are captured without truncation
- GIVEN a type error involving a user-defined type WHEN `/explain-error` inspects the type THEN it retrieves the type's full definition using `Print` or `About` and includes it in the explanation
- GIVEN a type error involving a type alias or abbreviation WHEN the types are inspected THEN the explanation shows both the abbreviated form and the expanded form to clarify the mismatch
- GIVEN a type error where the expected and actual types are structurally identical but differ by a module qualifier WHEN the types are inspected THEN the explanation identifies that two distinct but identically-named types are involved

**Traces to:** RTE-P0-1, RTE-P0-2

### Plain-Language Explanation

**Priority:** P0
**Stability:** Stable

- GIVEN a type error where the user passed a `nat` where a `bool` was expected WHEN `/explain-error` is invoked THEN the explanation states in plain language that the function expected a boolean argument but received a natural number, and identifies which argument position is wrong
- GIVEN a type error involving a function applied to too many or too few arguments WHEN `/explain-error` is invoked THEN the explanation states how many arguments the function expects, how many were provided, and which argument caused the error
- GIVEN any type error WHEN the explanation is produced THEN it avoids Coq jargon where possible and defines technical terms (e.g., "inductive type," "universe") when they are unavoidable
- GIVEN a unification failure between two complex types that differ in a single nested position WHEN `/explain-error` is invoked THEN the explanation pinpoints the specific sub-expression where the types diverge
- GIVEN a unification failure involving existential variables or metavariables WHEN `/explain-error` is invoked THEN the explanation notes that Coq was unable to infer a value for a particular position and suggests providing it explicitly
- GIVEN a unification failure WHEN the explanation is produced THEN it shows the two types aligned or annotated so the point of divergence is visually clear

**Traces to:** RTE-P0-3, RTE-P0-4

### Coercion Analysis

**Priority:** P1
**Stability:** Stable

- GIVEN a type mismatch where a coercion path exists from the actual type to the expected type WHEN `/explain-error` analyzes coercions THEN the explanation states that a coercion exists, names it, and explains why Coq did not apply it automatically (e.g., the coercion is not registered as a default, or a prerequisite was not met)
- GIVEN a type mismatch where no coercion path exists WHEN `/explain-error` analyzes coercions THEN the explanation states that no coercion is available and suggests that the user may need to define one or apply an explicit conversion
- GIVEN a type mismatch where multiple coercion paths exist WHEN `/explain-error` analyzes coercions THEN the explanation lists the available paths and notes any ambiguity

**Traces to:** RTE-P1-1

### Implicit Argument Mismatches

**Priority:** P1
**Stability:** Stable

- GIVEN a type error where an implicit argument was inferred to a surprising type WHEN `/explain-error` is invoked THEN the explanation identifies which implicit argument was inferred, what type it was inferred to, and why that inference conflicts with the rest of the term
- GIVEN an implicit argument mismatch WHEN a fix is suggested THEN it proposes providing the implicit argument explicitly using `@` notation, with the correct type filled in
- GIVEN a term with no implicit arguments WHEN `/explain-error` checks for implicit mismatches THEN it skips this analysis without producing spurious output

**Traces to:** RTE-P1-3

### Fix Suggestions

**Priority:** P1
**Stability:** Draft

- GIVEN a type error caused by a missing coercion WHEN a fix is suggested THEN it proposes either an explicit cast or an appropriate coercion declaration with correct syntax
- GIVEN a type error caused by applying a constructor to arguments in the wrong order WHEN a fix is suggested THEN it shows the correct argument order with the expected types labeled
- GIVEN a type error for which no clear fix can be determined WHEN `/explain-error` completes THEN it does not produce a misleading suggestion; instead it states that it could not determine a fix and provides diagnostic context for the user to investigate further

**Traces to:** RTE-P1-2

### Contextual Usage Examples

**Priority:** P1
**Stability:** Draft

- GIVEN a type error on a function application WHEN a usage example is requested THEN the explanation includes at least one example of a well-typed application of that function using types from the user's current environment
- GIVEN a type error involving a lemma or theorem WHEN a usage example is provided THEN it shows the lemma's type signature with each argument labeled and a sample instantiation
- GIVEN a type error on a definition with no obvious example WHEN the explanation is produced THEN this section is omitted rather than producing an unhelpful or incorrect example

**Traces to:** RTE-P1-5

### Notation and Scope Confusion

**Priority:** P1
**Stability:** Draft

- GIVEN a type error where a notation (e.g., `+`, `*`, `::`) was interpreted in a scope different from what the user intended WHEN `/explain-error` is invoked THEN the explanation identifies the notation, states which scope it was interpreted in, and shows what type it resolved to
- GIVEN a notation scope confusion WHEN a fix is suggested THEN it proposes either a `%scope` annotation or an `Open Scope` command to select the intended interpretation
- GIVEN a type error that does not involve notation ambiguity WHEN notation analysis is performed THEN it completes silently without producing spurious output

**Traces to:** RTE-P1-4

### Advanced Diagnostics

**Priority:** P2
**Stability:** Draft

- GIVEN a universe inconsistency error WHEN `/explain-error` is invoked THEN it retrieves the relevant universe constraints and identifies the cycle or contradictory pair in the constraint graph
- GIVEN a universe inconsistency WHEN the explanation is produced THEN it traces the conflicting constraints back to the definitions that introduced them, naming the specific `Definition`, `Inductive`, or `Lemma` declarations involved
- GIVEN a universe inconsistency WHEN a fix is suggested THEN it proposes concrete strategies such as universe polymorphism, `Set Universe Polymorphism`, or restructuring the type hierarchy
- GIVEN a type error where a canonical structure projection should have triggered but did not WHEN `/explain-error` is invoked THEN it identifies the relevant canonical structure and explains which condition of the projection rule was not met
- GIVEN a canonical structure failure WHEN the relevant structures are inspected THEN the explanation lists the registered canonical instances and shows which one was expected to match

**Traces to:** RTE-P2-1, RTE-P2-2

### Slash Command Integration

**Priority:** P0
**Stability:** Stable

- GIVEN a Coq type error in the current session WHEN the user invokes `/explain-error` THEN the slash command orchestrates error parsing, type inspection, and explanation generation, and returns a complete diagnostic within 15 seconds
- GIVEN no type error in the current context WHEN the user invokes `/explain-error` THEN it responds with a clear message that no type error was found to explain
- GIVEN a type error WHEN `/explain-error` completes THEN the output includes at minimum: a restatement of the error in plain language, the relevant type definitions, and an identification of the root cause
- GIVEN the `/explain-error` slash command WHEN it inspects types THEN it uses the vernacular introspection MCP tools (`Check`, `Print`, `About`) rather than raw Coq command strings
- GIVEN the `/explain-error` slash command WHEN it analyzes coercions THEN it uses the coercion-related MCP tools from the vernacular introspection initiative
- GIVEN a new MCP tool added to the Poule server WHEN it is relevant to type error diagnosis THEN the slash command can incorporate it without architectural changes to the command itself

**Traces to:** RTE-P0-5
