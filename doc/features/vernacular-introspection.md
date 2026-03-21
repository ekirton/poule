# Vernacular Introspection

A single MCP tool that gives Claude direct access to Coq's built-in vernacular introspection commands -- Print, Check, About, Locate, Search, Compute, and Eval -- so it can inspect types, unfold definitions, evaluate expressions, and locate names without the user acting as a relay between Claude Code and a Coq toplevel.

---

## Problem

Coq developers working with Claude Code today hit a wall every time they need to know what a definition expands to, what type a term has, or where a name lives. Claude cannot answer these questions from its training data alone -- Coq libraries evolve, user projects define their own constants, and proof contexts introduce local hypotheses that no static knowledge base covers. The only option is for the user to switch to a Coq toplevel (CoqIDE, Proof General, coq-lsp), run the command, copy the output, and paste it back into the conversation. This context-switching is slow, error-prone, and especially painful when Claude needs to chain several queries to build understanding -- for example, locating a name, printing its definition, and then checking the type of a subterm.

The Lean ecosystem avoids this problem because its language server exposes type and definition information programmatically, and tools like LeanDojo provide direct access to term evaluation. Coq has no equivalent path from an AI assistant to its introspection commands.

## Solution

The MCP server exposes a single `coq_query` tool that accepts a `command` parameter selecting which vernacular command to execute. The user (or Claude on the user's behalf) provides the command name and its arguments; the tool executes the command against the current Coq environment and returns the result.

### Definition inspection

The `Print` command shows the full body of a named constant, inductive type, or fixpoint -- the same output a developer would see in a Coq toplevel. This is the primary way to understand what a definition actually contains, as opposed to just its type signature. An optional `assumptions` variant lists the axioms a definition transitively depends on, which matters when assessing the trustworthiness of a proof.

### Type checking

The `Check` command shows the type of a term or expression. This covers both simple lookups ("what is the type of `Nat.add`?") and on-the-fly type inference for compound expressions ("what is the type of `fun n => n + 1`?"). When a proof session is active, `Check` resolves terms against the local proof context, so Claude can reason about hypotheses and let-bindings without the user having to spell them out.

### Name resolution

The `About` command retrieves metadata for a name: its kind (theorem, definition, inductive, constructor), defining module, and opacity status. The `Locate` command resolves short or partial names to fully qualified paths, disambiguating when multiple matches exist, and can also look up notation definitions. The `Search` command finds names matching a type pattern or constraint, which is how Claude discovers relevant lemmas when it does not know the exact name. Search results are truncated at a reasonable limit with an indication when truncation occurs, so large result sets do not overwhelm the conversation.

### Expression evaluation

The `Compute` command evaluates a term to its normal form -- full reduction. The `Eval` command does the same but under a specified reduction strategy (cbv, lazy, cbn, simpl, hnf, unfold), giving control over how far a term is reduced. Both commands work inside proof sessions, where they can reference local hypotheses and let-bindings. This lets Claude show a user what an expression actually computes to, or inspect an intermediate reduction form to understand why a tactic does or does not make progress.

## Design Rationale

### Why one tool, not seven

The [MCP Tool Surface](mcp-tool-surface.md) feature already occupies a significant share of the tool count budget. Each tool schema consumes context window tokens and adds cognitive load to tool selection. Because the seven vernacular commands share a common shape -- a command name and a textual argument, returning textual output -- bundling them under a single `coq_query` tool with a `command` parameter avoids inflating the tool count without sacrificing expressiveness. This is the opposite tradeoff from the search tools, where each tool has a distinct parameter shape and benefits from a semantic name.

### Why these commands

Print, Check, About, Locate, Search, Compute, and Eval are the vernacular commands Coq developers use daily for interactive exploration. They are read-only -- they inspect the environment without modifying it -- which keeps the tool safe to call at any time. Commands that modify state (Definition, Require, tactic execution) are out of scope; proof interaction is covered separately by the Proof Interaction Protocol.

### Session-aware, not session-free

Introspection commands run against whatever Coq environment the MCP server currently manages: loaded files, imported modules, and any active proof session. When a proof is in progress, commands automatically see local hypotheses and let-bindings. This means the user does not need to tell Claude "I'm in a proof" or re-state their context -- the tool picks it up from the session. The tradeoff is that results depend on session state, so the same query can return different results at different points in a development. This matches how Coq itself works and avoids the complexity of maintaining a separate stateless query endpoint.

## Acceptance Criteria

### Definition Inspection

**Priority:** P0
**Stability:** Stable

- GIVEN a valid fully qualified name of a defined constant WHEN the introspection tool is called with command `Print` and that name THEN the response includes the complete definition body as Coq would display it
- GIVEN a valid name of an inductive type WHEN the introspection tool is called with command `Print` THEN the response includes the inductive definition with all constructors
- GIVEN a name that does not exist in the current environment WHEN the introspection tool is called with command `Print` THEN a structured error is returned indicating the name was not found

### Print Assumptions

**Priority:** P1
**Stability:** Stable

- GIVEN a valid name of a defined constant or theorem WHEN the introspection tool is called with command `Print` and the `assumptions` option THEN the response lists all axioms the definition transitively depends on
- GIVEN a definition with no axiom dependencies WHEN the command is executed THEN the response indicates the definition is axiom-free

### Type Checking

**Priority:** P0
**Stability:** Stable

- GIVEN a well-typed Coq expression WHEN the introspection tool is called with command `Check` and that expression THEN the response includes the inferred type of the expression
- GIVEN a simple name of a lemma or constant WHEN the introspection tool is called with command `Check` THEN the response includes the type (statement) of that lemma or constant
- GIVEN an ill-typed expression WHEN the introspection tool is called with command `Check` THEN a structured error is returned including the Coq type error message
- GIVEN an active proof session with hypotheses in context WHEN the introspection tool is called with command `Check` and a term referencing a local hypothesis THEN the response includes the type of that term resolved against the proof context
- GIVEN an active proof session WHEN the introspection tool is called with command `Check` and a term that does not reference local hypotheses THEN the response includes the type resolved against the global environment as usual

### Metadata and Name Resolution

**Priority:** P0
**Stability:** Stable

- GIVEN a valid name WHEN the introspection tool is called with command `About` THEN the response includes the kind (e.g., Theorem, Definition, Inductive, Constructor), the defining module, and whether it is opaque or transparent
- GIVEN a name that does not exist in the current environment WHEN the introspection tool is called with command `About` THEN a structured error is returned indicating the name was not found
- GIVEN a short name that resolves to a unique fully qualified path WHEN the introspection tool is called with command `Locate` THEN the response includes the fully qualified name and its kind
- GIVEN a short name that resolves to multiple qualified paths WHEN the introspection tool is called with command `Locate` THEN the response includes all matching qualified names and their kinds
- GIVEN a name that cannot be located WHEN the introspection tool is called with command `Locate` THEN a structured error is returned indicating the name was not found
- GIVEN a notation string WHEN the introspection tool is called with command `Locate` THEN the response includes the notation's defining scope and interpretation

### Search

**Priority:** P0
**Stability:** Stable

- GIVEN a valid search pattern (e.g., a type fragment) WHEN the introspection tool is called with command `Search` and that pattern THEN the response includes a list of matching names with their types
- GIVEN a search pattern that matches no names WHEN the introspection tool is called with command `Search` THEN the response indicates no results were found
- GIVEN a search pattern that produces a large number of results WHEN the introspection tool is called THEN results are truncated at a reasonable limit and the response indicates truncation occurred

### Search with Scope Restriction

**Priority:** P1
**Stability:** Stable

- GIVEN a search pattern and a module scope qualifier WHEN the introspection tool is called with command `Search` and the scope restriction THEN only names within the specified module are returned
- GIVEN a scope qualifier that names a nonexistent module WHEN the introspection tool is called THEN a structured error is returned indicating the module was not found

### Expression Evaluation

**Priority:** P0
**Stability:** Stable

- GIVEN a well-typed Coq expression WHEN the introspection tool is called with command `Compute` and that expression THEN the response includes the fully reduced normal form of the expression
- GIVEN an ill-typed expression WHEN the introspection tool is called with command `Compute` THEN a structured error is returned including the Coq error message
- GIVEN a term whose reduction does not terminate within a reasonable time WHEN the introspection tool is called with command `Compute` THEN a structured error is returned indicating the computation timed out
- GIVEN a well-typed expression and a valid reduction strategy name WHEN the introspection tool is called with command `Eval` and the strategy and expression THEN the response includes the term reduced under that strategy
- GIVEN an invalid or unsupported strategy name WHEN the introspection tool is called with command `Eval` THEN a structured error is returned indicating the strategy is not recognized
- GIVEN the `unfold` strategy and a list of names to unfold WHEN the introspection tool is called THEN only the specified names are unfolded in the result
- GIVEN an active proof session with let-bound hypotheses WHEN the introspection tool is called with command `Compute` and a term referencing those hypotheses THEN the response includes the reduced form using the hypothesis values
- GIVEN an active proof session WHEN the introspection tool is called with command `Eval` with a strategy and a term referencing proof context THEN the response includes the term reduced under that strategy using the proof context

### Unified Tool Interface and Error Handling

**Priority:** P0
**Stability:** Stable

- GIVEN the MCP server is running WHEN the tool list is requested THEN there is exactly one new tool for vernacular introspection (not one per command)
- GIVEN the introspection tool WHEN it is called with a `command` parameter set to any of `Print`, `Check`, `About`, `Locate`, `Search`, `Compute`, or `Eval` THEN the corresponding Coq vernacular command is executed
- GIVEN the introspection tool WHEN it is called with an unrecognized command parameter THEN a structured error is returned listing the valid command values
- GIVEN any introspection command that fails WHEN the error is returned THEN the MCP response includes a structured error with the original command, the input that caused the error, and the Coq error message
- GIVEN a name-not-found error WHEN the error is returned THEN the error type is distinguishable from a type error or a malformed-command error
- GIVEN a malformed input (e.g., unparseable expression) WHEN the introspection tool is called THEN a structured error is returned indicating a parse failure with the Coq error message
- GIVEN no active proof session WHEN an introspection command is executed THEN it runs against the global Coq environment
- GIVEN an active proof session WHEN an introspection command is executed THEN it runs in the context of the current proof state, with access to local hypotheses and let-bindings
- GIVEN an active proof session WHEN the introspection tool is called with a term that references a local hypothesis by name THEN the command succeeds and uses the hypothesis from the proof context
