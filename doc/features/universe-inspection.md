# Universe Constraint Inspection

Tools for retrieving, filtering, and explaining Coq's universe constraints through natural language. When Claude encounters a universe inconsistency error — or when a user asks about the universe levels in their development — these tools let Claude surface the relevant constraints, trace them back to source definitions, and explain what went wrong and how to fix it.

---

## Problem

Universe inconsistency errors are among the most opaque in Coq. The error message names internal universe variables — `u.42`, `Top.37` — that bear no obvious relationship to anything the user wrote. Resolving the error requires a multi-step manual process: enable universe printing, dump the constraint graph, identify which definitions introduced the conflicting constraints, understand why the constraint solver cannot find a satisfying assignment, and then figure out what source-level change would eliminate the conflict. Even experienced users find this painful; intermediate users encountering their first universe error are often completely stuck.

The underlying Coq commands for inspecting universes exist and are mature — `Print Universes`, `Set Printing Universes`, `Print Universes Subgraph` — but they produce dense, unfiltered output that demands expert interpretation. No existing tool in the Coq ecosystem connects universe variables back to source definitions, explains constraint conflicts in plain language, or suggests concrete fixes.

## Solution

### Constraint Viewing

A user can ask Claude to show the universe constraints for any definition, lemma, or inductive type in a loaded Coq environment. Claude retrieves the constraints in structured form — universe variables, the relationships between them (less-than, less-than-or-equal, equal), and the definitions that introduced each constraint — and presents them in context. For definitions with no universe constraints, Claude explains why (e.g., the definition lives at `Set` level and involves no universe polymorphism).

When the user needs a broader view, Claude can retrieve the full universe constraint graph for the current environment or filter it to show only the constraints reachable from a specific definition. The filtered view is critical for large developments where the full graph may contain thousands of constraints: the user names a definition, and Claude returns only the relevant subgraph.

Claude can also show any term with explicit universe annotations — the equivalent of Coq's output under `Set Printing Universes` — so the user can see exactly which universe levels Coq assigned to each `Type` and `Sort` in a type signature.

### Inconsistency Diagnosis

When a user hits a `Universe inconsistency` error, they can paste the error message and ask Claude what went wrong. Claude identifies the specific constraints that form the inconsistent cycle, traces each constraint back to the definition or command that introduced it, and explains in plain language why those constraints are contradictory. The explanation references the user's source code — specific definitions and their relationships — rather than abstract universe variable names.

Claude also suggests at least one concrete resolution strategy: adding universe polymorphism to a definition, adjusting universe declarations, restructuring the code to avoid the conflicting constraint path, or other approaches appropriate to the specific error.

### Universe-Polymorphic Inspection

For users working with universe-polymorphic libraries, Claude can show how a polymorphic definition is instantiated at a specific use site — which concrete universe levels were substituted for each polymorphic variable. This is valuable when a type mismatch or universe error arises from unexpected instantiation.

Claude can also compare the universe levels of two definitions side by side, identifying whether their constraints are compatible and, if not, which constraint is more restrictive and why. This helps library authors understand why one definition cannot be used where another is expected.

## Design Rationale

Universe inconsistencies affect a small fraction of Coq users — primarily library authors, developers working with universe-polymorphic code, and anyone composing large-scale developments. But for those users, universe errors are disproportionately costly: they halt progress entirely and can take hours to debug manually. A tool that reduces diagnosis time by even half delivers significant value to the users who need it most.

The cost of providing this capability is low. Coq already exposes the necessary information through mature vernacular commands; the work is in wrapping those commands, parsing their output into structured form, and presenting the results through Claude's natural language interface. This makes universe inspection a high-value, low-cost addition to the tooling surface.

Universe inspection is a natural extension of the vernacular introspection tool. Where vernacular introspection provides general-purpose access to Coq's query commands (`Print`, `Check`, `About`, `Search`), universe inspection specializes in the subset of commands and output formats specific to the universe constraint system. The two capabilities share the same integration surface — sending commands to Coq and parsing structured responses — but universe inspection adds domain-specific parsing and explanation that generic introspection cannot provide. Keeping them as separate features reflects the distinct user need: a user debugging a universe error needs targeted diagnosis, not a general-purpose command interface.

## Acceptance Criteria

### Universe Constraint Retrieval

**Priority:** P0
**Stability:** Stable

- GIVEN a loaded Coq environment and a valid fully qualified name WHEN the universe-constraints tool is called with that name THEN it returns the universe variables and constraints associated with that definition in structured form
- GIVEN a name that does not exist in the current environment WHEN the universe-constraints tool is called THEN a structured error is returned indicating the name was not found
- GIVEN a definition with no universe constraints (e.g., a concrete, non-polymorphic definition at Set level) WHEN the universe-constraints tool is called THEN it returns an empty constraint set with an explanatory note
- GIVEN a loaded Coq environment WHEN the universe-graph tool is called THEN it returns the complete set of universe variables and constraints in structured form
- GIVEN the returned constraint graph WHEN it is inspected THEN each constraint includes the two universe expressions and the relationship (less-than, less-than-or-equal, or equal)
- GIVEN a large constraint graph WHEN the tool is called THEN the response completes within 3 seconds for environments up to the size of the Coq standard library
- GIVEN a valid term or definition name WHEN the print-with-universes tool is called THEN it returns the term with universe level annotations on every Type and Sort occurrence
- GIVEN a term that involves universe polymorphism WHEN the annotated term is returned THEN each polymorphic universe variable is labeled consistently across the output

### Universe Inconsistency Diagnosis

**Priority:** P0
**Stability:** Stable

- GIVEN a universe inconsistency error message and the current Coq environment WHEN the diagnose-universe-error tool is called THEN it identifies the specific constraints that form the inconsistent cycle
- GIVEN the identified conflicting constraints WHEN the diagnosis is returned THEN each constraint is traced back to the definition or command that introduced it
- GIVEN a diagnosis WHEN it is presented THEN it includes a plain-language explanation of why the constraints are contradictory and at least one suggested resolution strategy
- GIVEN an error message that is not a universe inconsistency error WHEN the tool is called THEN a structured error is returned indicating the error type is not supported
- GIVEN a universe inconsistency error and the source file where it occurred WHEN the explanation tool is called THEN the explanation references specific lines or definitions in the user's source code, not just abstract universe variable names
- GIVEN the explanation WHEN a user with intermediate Coq knowledge reads it THEN it describes what universe levels are, why the conflict arose, and what concrete change to the source code would resolve it

### Universe-Polymorphic Instantiation Inspection

**Priority:** P1
**Stability:** Stable

- GIVEN a universe-polymorphic definition and a use site (identified by definition name or location) WHEN the inspect-instantiation tool is called THEN it returns the concrete universe levels substituted for each polymorphic universe variable at that use site
- GIVEN a definition that is not universe-polymorphic WHEN the tool is called THEN a structured response is returned indicating the definition is monomorphic and has no universe parameters to instantiate
- GIVEN two valid definition names WHEN the compare-universes tool is called THEN it returns the universe constraints of each definition and identifies any constraints that would be violated if one were substituted for the other
- GIVEN two definitions with compatible universe levels WHEN the comparison is returned THEN it confirms compatibility and shows the constraint alignment
- GIVEN two definitions with incompatible universe levels WHEN the comparison is returned THEN it identifies the specific constraint conflict and explains which definition's constraint is more restrictive

### Filtered Constraint Graph

**Priority:** P1
**Stability:** Stable

- GIVEN a valid definition name WHEN the filtered-universe-graph tool is called THEN it returns only the universe variables and constraints transitively reachable from that definition's universe variables
- GIVEN a definition with no universe variables WHEN the tool is called THEN it returns an empty graph with an explanatory note
- GIVEN a definition whose reachable subgraph contains N constraints WHEN the full graph contains M >> N constraints THEN the filtered result contains exactly N constraints

### Structured Output

**Priority:** P0
**Stability:** Stable

- GIVEN any universe inspection tool WHEN the response is returned THEN constraint data is structured with fields for universe variables, constraint expressions, relationship type, and source definition
- GIVEN structured constraint output WHEN it is serialized as JSON THEN it conforms to a declared schema
- GIVEN raw Coq output from `Print Universes` or `Set Printing Universes` WHEN it is processed by the tool THEN the structured output preserves all information present in the raw output without loss
