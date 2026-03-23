You are executing the `/explain-error` command. Your job is to diagnose a Coq type error: parse it, gather context using MCP tools, explain what went wrong in plain language, and suggest concrete fixes.

## Step 1: Obtain the error

Check these sources in order until you have an error to work with:

1. The user provided an error message directly in the conversation. Use it as-is.
2. Look for a recent Coq error in the conversation history (e.g., from a build or proof attempt).
3. If neither is available, look for a `_CoqProject` or `Makefile` in the project and run a build with Bash (`make 2>&1` or `coq_makefile` equivalent). Capture stderr.
4. If no error can be found or produced, tell the user: "No type error found. Paste an error message or point me to a file to compile."

Stop here if the error is not a type error (e.g., syntax error, tactic failure, missing reference). Tell the user this command handles type errors and briefly describe what their error appears to be instead.

## Step 2: Parse the error

Extract these fields from the error message:

- **Error pattern**: Identify which class of error this is (see classification below).
- **Term**: The term that is ill-typed.
- **Expected type**: What Coq expected.
- **Actual type**: What the term actually has.
- **Location**: File, line, and character offset if present.
- **Environment**: Any local variable bindings shown in "In environment ..." blocks.
- **Source expression**: If you can identify the file and location, use Read to get the surrounding source code (10-15 lines of context around the error site).

### Error classification

Classify the error into one of these categories:

| Category | Typical error message pattern |
|---|---|
| **Type mismatch** | "The term X has type T1 while it is expected to have type T2" |
| **Unification failure** | "Unable to unify T1 with T2" |
| **Wrong number of arguments** | "X is applied to too many/few arguments" |
| **Universe inconsistency** | "Universe inconsistency" or "Cannot enforce ... because ..." |
| **Missing coercion** | Type mismatch where expected and actual types are related but not identical |
| **Notation/scope confusion** | Type mismatch involving operators like `+`, `*`, `::` where the types suggest the wrong scope |
| **Implicit argument mismatch** | Type mismatch where the inferred types seem surprising given the explicit arguments |
| **Canonical structure failure** | "Cannot find a canonical structure" or projection-related unification failures |

## Step 3: Gather context with MCP tools

Run these tool calls based on the error category. Gather all applicable context before producing the explanation. Make independent tool calls in parallel when possible.

### For all type errors:

1. **Inspect the expected type**: `vernacular_query` with command `Print <expected_type>` to get its full definition. If it is an alias or abbreviation, this reveals what it expands to.
2. **Inspect the actual type**: `vernacular_query` with command `Print <actual_type>` similarly.
3. **Check the offending term**: `vernacular_query` with command `Check <term>` to see its inferred type in context (if the term is a named definition or can be checked in isolation).
4. **Get info on key identifiers**: `vernacular_query` with command `About <identifier>` for any function, constructor, or lemma at the error site. This reveals implicit arguments, scopes, and other metadata.

### Additional context by error category:

**Type mismatch / Unification failure:**
- If the types share a head symbol but differ in arguments, `Print` both to compare their structure.
- If the types have the same short name but might come from different modules, `vernacular_query` with `Locate <name>` to check for ambiguity.
- Use `search_by_type` to find functions or lemmas that could convert between the two types.

**Missing coercion:**
- `vernacular_query` with `Print Coercions` to list available coercions.
- `vernacular_query` with `Print Graph` to see the coercion graph.
- `search_by_name` or `search_by_type` to look for explicit conversion functions between the two types.

**Notation/scope confusion:**
- `vernacular_query` with `Locate "notation"` (e.g., `Locate "+"`) to see which scopes define it.
- `vernacular_query` with `Print Scope <scope_name>` for relevant scopes to see what the notation means in each.

**Implicit argument mismatch:**
- `vernacular_query` with `About <function>` to see which arguments are implicit.
- `vernacular_query` with `Print Implicit <function>` for detailed implicit argument info.

**Universe inconsistency:**
- `vernacular_query` with `Print Universes` if feasible.
- `vernacular_query` with `About <definition>` for each definition mentioned in the constraint chain to identify where the universe constraints originate.

**Canonical structure failure:**
- `vernacular_query` with `Print Canonical Projections` to list registered instances.
- `vernacular_query` with `About <structure>` to inspect the structure definition.

**Wrong number of arguments:**
- `vernacular_query` with `Check <function>` and `About <function>` to show the full type signature and how many arguments it expects.

## Step 4: Construct the explanation

Write a plain-language explanation with this structure:

### What went wrong

State the problem in one to three sentences that a Coq user who does not fluently read type expressions can understand. Name the specific argument position, sub-expression, or definition where the conflict arises. Avoid restating the raw error -- interpret it.

Example: "The second argument to `List.map` should be a `list nat`, but you passed a `list bool`. The function `f` you are mapping has type `nat -> nat`, so the input list must contain natural numbers."

### Why it happened

Explain the root cause. This is where you use the context gathered in Step 3:

- If types look the same but come from different modules, say so and name the modules.
- If an implicit argument was inferred to something unexpected, show what was inferred and why.
- If a coercion should have fired but did not, explain which coercion exists and what prevented it.
- If a notation was interpreted in the wrong scope, show the scope it was interpreted in and what it resolved to.
- If the types are structurally similar, pinpoint the exact sub-expression where they diverge.

Include the relevant type definitions you fetched, but present them as supporting evidence, not as the explanation itself.

### Technical details

For users who want the full picture, include:

- The exact expected and actual types from the error.
- Relevant definitions you retrieved (abbreviated if they are very long).
- The coercion graph excerpt or scope information if applicable.

## Step 5: Suggest fixes

Provide one or more concrete fix suggestions. Each suggestion should include actual code the user can use or adapt. Order suggestions from most likely correct to least.

Common fix patterns:

| Error type | Fix pattern |
|---|---|
| Simple type mismatch | Show the correct type or correct argument to use |
| Wrong argument order | Show the corrected application with arguments reordered |
| Missing coercion | Propose an explicit cast, or a `Coercion` declaration with exact syntax |
| Notation/scope confusion | Propose `%scope` annotation (e.g., `(x + y)%nat`) or `Open Scope` command |
| Implicit argument mismatch | Propose `@function` with explicit arguments filled in |
| Universe inconsistency | Propose `Polymorphic` or `Universe` declarations, or restructuring |
| Unification with metavariables | Propose explicit type annotation to guide inference |

If you find a relevant lemma or function via `search_by_type` or `search_by_name` that would resolve the issue, include it in the suggestion.

If you cannot determine a fix with confidence, say so explicitly. Do not guess. Provide the diagnostic context you have gathered so the user can investigate further.

## Step 5b: Add educational context

After suggesting fixes, call `education_context` with a query describing the error category and relevant Coq concept (e.g., "type mismatch in function application", "universe inconsistency", "coercion between types").

If relevant Software Foundations content is found, add a brief **See also** note:
- One sentence summarizing the relevant SF teaching on this concept.
- Citation: "Software Foundations, {location}" with the browser path.
- Suggest: "Run `/textbook [concept]` for a deeper explanation."

Keep this annotation brief. If `education_context` returns an error or no results, skip this step silently.

## Step 6: Handle edge cases

**Multiple errors:** If the build produced multiple type errors, diagnose the first one only. Tell the user how many additional errors were found and suggest running `/explain-error` again after fixing the first.

**Error in a dependency:** If the error originates in a file the user did not write (a library or dependency), say so. Explain what the user's code did that triggered it and focus the fix on the user's code.

**Non-type errors that slip through:** If you classified the error as a type error but further inspection reveals it is something else (e.g., a tactic-generated subgoal that failed to unify), adjust your explanation accordingly. Do not force a type-error framing onto a different kind of problem.

**Extremely long types:** If the expected or actual types are more than 10 lines when printed, summarize their top-level structure and focus on the point of divergence rather than reproducing them in full. Show the full types in the technical details section only if the user would benefit from seeing them.

**No MCP server available:** If MCP tool calls fail (server not running, connection error), fall back to analyzing the error message text and any source code you can read with standard Claude Code tools (Read, Grep, Glob). Explain that deeper inspection was not available and the analysis is based on the error message alone.
