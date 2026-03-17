# User Stories: Type Error Explanation

Derived from [doc/requirements/type-error-explanation.md](../type-error-explanation.md).

---

## Epic 1: Error Parsing and Type Inspection

### 1.1 Parse a Coq Type Error

**As a** Coq user who has encountered a type error,
**I want** the `/explain-error` command to parse the error message and extract the expected type, actual type, and source location,
**so that** the diagnostic workflow starts from structured information rather than raw text.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq type error of the form "The term X has type T1 while it is expected to have type T2" WHEN `/explain-error` is invoked THEN it correctly extracts the term, the actual type, and the expected type as separate structured fields
- GIVEN a type error that includes an environment context ("In environment ...") WHEN the error is parsed THEN the local variable bindings from the environment are extracted and available for subsequent inspection
- GIVEN a type error that spans multiple lines due to complex types WHEN the error is parsed THEN the full types are captured without truncation

**Traces to:** RTE-P0-1

### 1.2 Inspect Type Definitions in Context

**As a** Coq user trying to understand a type mismatch,
**I want** the `/explain-error` command to fetch the definitions of the types involved in the error,
**so that** I can see what the expected and actual types really are, including any unfolded definitions or parameters.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a type error involving a user-defined type WHEN `/explain-error` inspects the type THEN it retrieves the type's full definition using `Print` or `About` and includes it in the explanation
- GIVEN a type error involving a type alias or abbreviation WHEN the types are inspected THEN the explanation shows both the abbreviated form and the expanded form to clarify the mismatch
- GIVEN a type error where the expected and actual types are structurally identical but differ by a module qualifier WHEN the types are inspected THEN the explanation identifies that two distinct but identically-named types are involved

**Traces to:** RTE-P0-2

---

## Epic 2: Plain-Language Explanation

### 2.1 Explain a Simple Type Mismatch

**As a** newcomer to Coq who does not yet fluently read type expressions,
**I want** the `/explain-error` command to explain in plain language what the type mismatch means,
**so that** I can understand the error without needing to manually decode Coq's type syntax.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a type error where the user passed a `nat` where a `bool` was expected WHEN `/explain-error` is invoked THEN the explanation states in plain language that the function expected a boolean argument but received a natural number, and identifies which argument position is wrong
- GIVEN a type error involving a function applied to too many or too few arguments WHEN `/explain-error` is invoked THEN the explanation states how many arguments the function expects, how many were provided, and which argument caused the error
- GIVEN any type error WHEN the explanation is produced THEN it avoids Coq jargon where possible and defines technical terms (e.g., "inductive type," "universe") when they are unavoidable

**Traces to:** RTE-P0-3

### 2.2 Explain Unification Failures

**As a** Coq user who encounters "Unable to unify" errors,
**I want** the `/explain-error` command to identify the specific sub-terms that failed to unify,
**so that** I can see exactly where the types diverge rather than comparing two large type expressions manually.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a unification failure between two complex types that differ in a single nested position WHEN `/explain-error` is invoked THEN the explanation pinpoints the specific sub-expression where the types diverge
- GIVEN a unification failure involving existential variables or metavariables WHEN `/explain-error` is invoked THEN the explanation notes that Coq was unable to infer a value for a particular position and suggests providing it explicitly
- GIVEN a unification failure WHEN the explanation is produced THEN it shows the two types aligned or annotated so the point of divergence is visually clear

**Traces to:** RTE-P0-4

---

## Epic 3: Coercion Analysis

### 3.1 Analyze Coercion Paths

**As a** Coq user whose type error involves types that should be coercible,
**I want** the `/explain-error` command to check whether a coercion path exists between the expected and actual types,
**so that** I can understand whether a coercion should have been applied and why it was not.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a type mismatch where a coercion path exists from the actual type to the expected type WHEN `/explain-error` analyzes coercions THEN the explanation states that a coercion exists, names it, and explains why Coq did not apply it automatically (e.g., the coercion is not registered as a default, or a prerequisite was not met)
- GIVEN a type mismatch where no coercion path exists WHEN `/explain-error` analyzes coercions THEN the explanation states that no coercion is available and suggests that the user may need to define one or apply an explicit conversion
- GIVEN a type mismatch where multiple coercion paths exist WHEN `/explain-error` analyzes coercions THEN the explanation lists the available paths and notes any ambiguity

**Traces to:** RTE-P1-1

### 3.2 Explain Implicit Argument Mismatches

**As a** Coq user confused by a type error that seems to involve the wrong types,
**I want** the `/explain-error` command to check whether Coq's implicit argument inference filled in an unexpected type,
**so that** I can understand that the error is caused by inference rather than by my explicit code.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a type error where an implicit argument was inferred to a surprising type WHEN `/explain-error` is invoked THEN the explanation identifies which implicit argument was inferred, what type it was inferred to, and why that inference conflicts with the rest of the term
- GIVEN an implicit argument mismatch WHEN a fix is suggested THEN it proposes providing the implicit argument explicitly using `@` notation, with the correct type filled in
- GIVEN a term with no implicit arguments WHEN `/explain-error` checks for implicit mismatches THEN it skips this analysis without producing spurious output

**Traces to:** RTE-P1-3

---

## Epic 4: Fix Suggestions

### 4.1 Suggest Fixes for Common Type Errors

**As a** Coq user who understands what went wrong but does not know how to fix it,
**I want** the `/explain-error` command to suggest concrete fixes,
**so that** I can resolve the error without searching through documentation or library source code.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a type error caused by a missing coercion WHEN a fix is suggested THEN it proposes either an explicit cast or an appropriate coercion declaration with correct syntax
- GIVEN a type error caused by applying a constructor to arguments in the wrong order WHEN a fix is suggested THEN it shows the correct argument order with the expected types labeled
- GIVEN a type error for which no clear fix can be determined WHEN `/explain-error` completes THEN it does not produce a misleading suggestion; instead it states that it could not determine a fix and provides diagnostic context for the user to investigate further

**Traces to:** RTE-P1-2

### 4.2 Provide Contextual Usage Examples

**As a** Coq user who keeps misusing a particular definition or tactic,
**I want** the `/explain-error` command to show me a correct usage example for the definition that produced the error,
**so that** I can learn the right pattern and avoid repeating the mistake.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a type error on a function application WHEN a usage example is requested THEN the explanation includes at least one example of a well-typed application of that function using types from the user's current environment
- GIVEN a type error involving a lemma or theorem WHEN a usage example is provided THEN it shows the lemma's type signature with each argument labeled and a sample instantiation
- GIVEN a type error on a definition with no obvious example WHEN the explanation is produced THEN this section is omitted rather than producing an unhelpful or incorrect example

**Traces to:** RTE-P1-5

---

## Epic 5: Notation and Scope Confusion

### 5.1 Explain Notation-Related Type Errors

**As a** Coq user whose type error was caused by a notation being interpreted in the wrong scope,
**I want** the `/explain-error` command to detect this situation and explain what the notation actually means,
**so that** I can understand that the error is about notation scope rather than a genuine type mismatch in my logic.

**Priority:** P1
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a type error where a notation (e.g., `+`, `*`, `::`) was interpreted in a scope different from what the user intended WHEN `/explain-error` is invoked THEN the explanation identifies the notation, states which scope it was interpreted in, and shows what type it resolved to
- GIVEN a notation scope confusion WHEN a fix is suggested THEN it proposes either a `%scope` annotation or an `Open Scope` command to select the intended interpretation
- GIVEN a type error that does not involve notation ambiguity WHEN notation analysis is performed THEN it completes silently without producing spurious output

**Traces to:** RTE-P1-4

---

## Epic 6: Advanced Diagnostics

### 6.1 Diagnose Universe Inconsistency Errors

**As an** advanced Coq user who encounters a universe inconsistency,
**I want** the `/explain-error` command to inspect the universe constraint graph and explain the conflicting path,
**so that** I can understand which definitions introduced the conflicting constraints and how to restructure my code.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a universe inconsistency error WHEN `/explain-error` is invoked THEN it retrieves the relevant universe constraints and identifies the cycle or contradictory pair in the constraint graph
- GIVEN a universe inconsistency WHEN the explanation is produced THEN it traces the conflicting constraints back to the definitions that introduced them, naming the specific `Definition`, `Inductive`, or `Lemma` declarations involved
- GIVEN a universe inconsistency WHEN a fix is suggested THEN it proposes concrete strategies such as universe polymorphism, `Set Universe Polymorphism`, or restructuring the type hierarchy

**Traces to:** RTE-P2-1

### 6.2 Explain Canonical Structure Projection Failures

**As an** advanced Coq user working with canonical structures,
**I want** the `/explain-error` command to explain when a canonical structure projection failed to trigger,
**so that** I can understand why the expected unification hint was not applied.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a type error where a canonical structure projection should have triggered but did not WHEN `/explain-error` is invoked THEN it identifies the relevant canonical structure and explains which condition of the projection rule was not met
- GIVEN a canonical structure failure WHEN the relevant structures are inspected THEN the explanation lists the registered canonical instances and shows which one was expected to match

**Traces to:** RTE-P2-2

---

## Epic 7: Slash Command Integration

### 7.1 End-to-End Slash Command Workflow

**As a** Coq user working in Claude Code,
**I want** to type `/explain-error` and receive a complete diagnostic without any further manual steps,
**so that** the entire error diagnosis workflow is a single action.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN a Coq type error in the current session WHEN the user invokes `/explain-error` THEN the slash command orchestrates error parsing, type inspection, and explanation generation, and returns a complete diagnostic within 15 seconds
- GIVEN no type error in the current context WHEN the user invokes `/explain-error` THEN it responds with a clear message that no type error was found to explain
- GIVEN a type error WHEN `/explain-error` completes THEN the output includes at minimum: a restatement of the error in plain language, the relevant type definitions, and an identification of the root cause

**Traces to:** RTE-P0-5

### 7.2 Orchestrate MCP Tools as Building Blocks

**As a** Coq user who benefits from Poule's MCP tools,
**I want** the `/explain-error` command to use the same MCP tools that are available for other workflows (vernacular introspection, notation inspection, universe inspection),
**so that** the diagnostic draws on the full power of the Poule toolset rather than reimplementing inspection capabilities.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN the `/explain-error` slash command WHEN it inspects types THEN it uses the vernacular introspection MCP tools (`Check`, `Print`, `About`) rather than raw Coq command strings
- GIVEN the `/explain-error` slash command WHEN it analyzes coercions THEN it uses the coercion-related MCP tools from the vernacular introspection initiative
- GIVEN a new MCP tool added to the Poule server WHEN it is relevant to type error diagnosis THEN the slash command can incorporate it without architectural changes to the command itself

**Traces to:** RTE-P0-5
