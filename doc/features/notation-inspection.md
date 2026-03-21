# Notation Inspection

Claude gains the ability to look up what any Coq notation means, find where it is defined, list the notations available in a scope, explain how precedence and associativity affect parsing, disambiguate notations that appear in multiple scopes, and guide users in writing new notation declarations -- all through natural-language interaction backed by Coq's own introspection commands.

---

## Problem

Coq notations are powerful but arcane. Every serious Coq development layers custom notations over the base syntax -- `_ ++ _` for list append, `{ x : T | P }` for sigma types, `_ =? _` for decidable equality, and hundreds more across libraries like MathComp, Iris, and stdpp. Notations make finished code readable, but they make unfamiliar code impenetrable. When a user encounters a symbol they do not recognize, answering the question "what does this mean?" is unreasonably hard.

The existing commands for notation inspection (`Locate Notation`, `Print Notation`, `Print Scope`, `Print Visibility`) are individually capable but collectively hostile to casual use. `Locate Notation` requires the user to quote the notation string in a format that differs from the surface syntax in non-obvious ways. `Print Scope` dumps every notation in a scope -- sometimes dozens or hundreds of entries -- with no filtering or explanation. `Print Visibility` describes scope stacking order in terms that presuppose expertise. None of these commands surface the information users most often need -- what does this notation expand to, what is its precedence, why did Coq pick this interpretation instead of that one -- in a single query.

The result is that users resort to searching through source files, asking on forums, or simply guessing. Beginners are blocked by symbols they cannot decode. Intermediate users working with third-party libraries waste time navigating notation conventions they have never seen before. Advanced users defining new notations endure trial-and-error cycles to get the syntax, precedence, and associativity right.

## Solution

### Notation lookup

Given a notation string or a term that uses a notation, Claude retrieves the notation's expansion -- the underlying Coq term it desugars to -- along with the scope it was resolved from and the module where it is defined. The user can provide the notation in its natural surface syntax; quoting conventions are handled internally so the user never needs to know how Coq expects notation strings to be quoted for `Locate Notation` or `Print Notation`.

When the user provides a term rather than a bare notation string, Claude identifies which notation was used and retrieves the same information. This covers the common case where a user points at a line of code and asks "what does this mean?" without needing to isolate the notation themselves.

### Scope inspection

Claude can list all notations registered in a given scope, making it possible to explore a library's notation surface without reading its source code. A user working with `list_scope` for the first time can ask what notations are available and receive every registered entry with its notation string and expansion.

Claude can also show which scopes are currently open and their stacking order, explaining what it means for scope resolution. When a notation appears in multiple open scopes, the scope list clarifies which interpretation Coq will select by default and why -- the most recently opened scope takes priority, or a type-directed scope binding overrides the default ordering.

### Precedence and associativity

For any notation, Claude can report its precedence level (0 through 200), associativity (left, right, or none), and format string if one exists. Users confused by unexpected parse results -- "why does `a + b * c` parse as `a + (b * c)` and not `(a + b) * c`?" -- get a direct explanation grounded in the actual precedence and associativity values rather than a generic rule of thumb.

When a notation carries `only parsing` or `only printing` flags, those are included in the explanation, since they affect whether the notation appears in Coq's output or is only accepted as input.

### Ambiguity handling

When a notation has interpretations in multiple open scopes, Claude lists all of them, marks which one is currently active, and explains why that interpretation was selected based on the scope priority order. This directly addresses the "notation is ambiguous" warnings that confuse users.

For users who want a non-default interpretation, Claude explains the mechanisms for selecting it: inline `%scope_key` delimiters to override resolution at a single use site, or `Open Scope` and `Close Scope` commands to change the default resolution for an entire section of code.

### Authoring guidance

Users defining new notations can describe their intent in natural language -- "an infix operator for my custom addition, at precedence 50, left-associative" -- and receive a syntactically correct `Notation` or `Infix` command. When the suggested notation would conflict with an existing in-scope notation (same symbol, overlapping precedence), a warning is included so the user can adjust before committing the definition.

Claude can also explain the differences between `Notation`, `Infix`, and `Abbreviation`, recommending which form best suits a given situation based on whether the user needs custom syntax, a simple binary operator, or an unfoldable shorthand.

## Design Rationale

### Why notations are a universal pain point

Notations are unlike most Coq features in that every user encounters them constantly but few users understand how they work. A beginner reading Software Foundations hits custom notations in the first chapter. An intermediate user importing MathComp inherits hundreds of notations with no onboarding. An expert defining notations for a new library fights a system with over 200 precedence levels, three associativity options, format strings, scope bindings, and parsing-only versus printing-only flags. The notation system is one of the few parts of Coq where the gap between "uses it daily" and "understands it" is widest, making it a high-value target for tool support.

### Relationship to vernacular introspection

The underlying Coq commands for notation inspection -- `Locate Notation`, `Print Notation`, `Print Scope`, `Print Visibility` -- are vernacular introspection commands, closely related to the `Print`, `Check`, `About`, `Locate`, and `Search` commands exposed by [Vernacular Introspection](vernacular-introspection.md). The two features may share the same MCP tool at the implementation level, with notation-specific commands exposed as additional `command` variants under the existing `coq_query` tool rather than as separate tools. This avoids inflating the tool count and keeps the interface consistent: one tool for read-only queries against the Coq environment, whether the user is asking about a definition, a type, or a notation. The decision on whether to bundle or separate is an architecture concern; from the user's perspective, the distinction is invisible -- they ask about a notation and get an answer.

---

## Acceptance Criteria

### Look Up What a Notation Means

**Priority:** P0
**Stability:** Stable

- GIVEN a loaded Coq project and a notation string (e.g., `_ ++ _`) WHEN the lookup tool is called THEN it returns the notation's expansion showing the underlying Coq term it desugars to
- GIVEN a term that uses a notation (e.g., `[1; 2; 3]`) WHEN the lookup tool is called THEN it returns the notation's expansion and the scope it was resolved from
- GIVEN a notation string that does not match any in-scope notation WHEN the lookup tool is called THEN a structured error is returned indicating the notation was not found
- GIVEN a valid notation WHEN the result is returned THEN it includes the notation string, the expanded term, the defining scope, and the defining module

### Find Where a Notation Is Defined

**Priority:** P0
**Stability:** Stable

- GIVEN a notation string WHEN the locate tool is called THEN it returns the fully qualified module path where the notation is defined
- GIVEN a notation that is defined in multiple scopes WHEN the locate tool is called THEN it returns all defining locations, one per scope, with the currently active interpretation marked
- GIVEN a notation string that requires non-obvious quoting (e.g., containing single quotes or underscores) WHEN the user provides the notation in its surface syntax THEN the tool handles quoting internally and returns the correct result

### List Notations in a Scope

**Priority:** P0
**Stability:** Stable

- GIVEN a valid scope name (e.g., `list_scope`, `nat_scope`) WHEN the list-scope tool is called THEN it returns all notations registered in that scope, each with its notation string and expansion
- GIVEN an invalid or nonexistent scope name WHEN the list-scope tool is called THEN a structured error is returned indicating the scope was not found
- GIVEN a scope with more than 20 notations WHEN the result is returned THEN all notations are included (no truncation)

### Show Active Scopes and Resolution Order

**Priority:** P1
**Stability:** Stable

- GIVEN a loaded Coq environment WHEN the show-visibility tool is called THEN it returns the list of open scopes in priority order (most recently opened first)
- GIVEN the scope list WHEN it is returned THEN each entry includes the scope name and, if applicable, the type it is bound to
- GIVEN a notation that appears in multiple open scopes WHEN the show-visibility tool is called with that notation THEN the result indicates which scope's interpretation is active and why

### Explain Notation Precedence and Associativity

**Priority:** P0
**Stability:** Stable

- GIVEN a notation string WHEN the precedence tool is called THEN it returns the notation's precedence level (0-200), associativity (left, right, or none), and format string if one is defined
- GIVEN two notation strings WHEN both are queried THEN the user can compare their precedence levels to understand parsing order
- GIVEN a notation with `only parsing` or `only printing` flags WHEN the result is returned THEN those flags are included in the metadata

### Explain How a Compound Expression Is Parsed

**Priority:** P1
**Stability:** Draft

- GIVEN a Coq expression using multiple notations WHEN the explain-parse tool is called THEN it returns the fully parenthesized form showing how precedence and associativity resolved the expression
- GIVEN an expression that is ambiguous or ill-formed due to notation conflicts WHEN the tool is called THEN a structured error is returned explaining the ambiguity

### List All Interpretations of an Ambiguous Notation

**Priority:** P0
**Stability:** Stable

- GIVEN a notation string that has interpretations in multiple open scopes WHEN the disambiguate tool is called THEN it returns all interpretations, each with the scope name, expansion, and whether it is the currently active interpretation
- GIVEN the list of interpretations WHEN one is the active interpretation THEN it is clearly marked and the reason for its selection (scope priority order) is included
- GIVEN a notation with only one interpretation in scope WHEN the disambiguate tool is called THEN it returns that single interpretation with a note that there is no ambiguity

### Suggest How to Select a Specific Interpretation

**Priority:** P1
**Stability:** Stable

- GIVEN an ambiguous notation and a user-selected target interpretation WHEN the tool is asked for guidance THEN it suggests the appropriate `%scope_key` delimiter to apply inline
- GIVEN an ambiguous notation WHEN the tool provides guidance THEN it also explains how `Open Scope` and `Close Scope` commands can change the default resolution

### Suggest a Notation Definition

**Priority:** P1
**Stability:** Draft

- GIVEN a description of the desired notation (symbol, arity, precedence, associativity) WHEN the suggest-notation tool is called THEN it returns a syntactically correct `Notation` or `Infix` command
- GIVEN the suggested command WHEN it is evaluated in Coq THEN it is accepted without syntax errors
- GIVEN a request that would conflict with an existing notation in scope WHEN the suggestion is generated THEN a warning is included noting the potential conflict
