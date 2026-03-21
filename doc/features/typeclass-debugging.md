# Typeclass Debugging

Typeclass debugging gives Claude the ability to inspect registered instances, trace the resolution engine's search process, and explain — in plain language — why resolution succeeded, failed, or chose one instance over another. A Coq developer encountering a typeclass error asks Claude what went wrong; Claude runs the appropriate debugging commands, interprets the output, and returns a clear explanation without the developer ever needing to know which Coq vernacular to invoke.

---

## Problem

Typeclass resolution failures produce cryptic error messages. Coq tells the user that resolution failed but says almost nothing about why — which instances were tried, which came close to matching, or what the resolution engine was searching for. Users waste significant time on what should be a straightforward diagnostic task.

The debugging tools exist. `Set Typeclasses Debug` produces a resolution trace; `Print Instances` lists registered instances; `Print Typeclasses` enumerates known typeclasses. But these tools are hard to discover, their output is unstructured and verbose, and interpreting that output requires expert knowledge of how the resolution engine works. A newcomer encountering their first typeclass error has no realistic path from the error message to the root cause. Even experienced Coq developers routinely spend tens of minutes manually parsing indentation levels in debug traces to reconstruct the resolution search tree.

No existing tool — IDE, CLI, or otherwise — interprets this debug output or explains it. The information is there; it is just inaccessible.

## Solution

Claude acts as an interpreter between the user and Coq's typeclass debugging commands. The user describes the problem in natural language; Claude invokes the right commands, reads their output, and returns a structured explanation. Four capabilities compose the feature.

### Instance Listing

Given a typeclass name, Claude lists every registered instance: the instance name, its type signature, and the module where it is defined. This is the starting point for most debugging sessions — the user needs to see what instances exist before reasoning about why one was or was not selected. When no instances exist for a typeclass, Claude says so explicitly rather than returning an empty result that the user must interpret. When the name does not refer to a typeclass, Claude reports that clearly rather than producing a confusing Coq error.

Claude can also list all registered typeclasses in the current environment with summary information — how many instances each has, whether default instances are present — giving library authors an overview of the typeclass landscape they are working within.

### Resolution Tracing

When the user has a proof state where typeclass resolution is failing (or succeeding unexpectedly), Claude traces the resolution process for that goal. The trace shows which instances were tried, in what order, and whether each succeeded or failed. Rather than dumping the raw output of `Set Typeclasses Debug`, Claude parses the trace into a structured account: each step identifies the instance, the goal it was applied to, and the outcome.

For complex resolutions, Claude can present the full search tree — branching points where multiple instances were candidates, the engine's choice at each branch, and the reasons alternatives were rejected. The user sees the resolution logic laid out clearly instead of reverse-engineering it from indentation levels in a log.

### Failure Explanation

When resolution fails, Claude identifies and explains the root cause. There are three common failure modes, and each gets a different explanation:

- **No matching instance.** Claude identifies the specific typeclass and type arguments that lack an instance, and names what is missing.
- **Unification failure.** Claude identifies the instance that came closest to matching and explains which type arguments failed to unify and why.
- **Resolution depth exceeded.** Claude recognizes the depth limit error, shows the resolution path that led to the loop or deep chain, and explains the cycle.

The user gets a diagnosis, not a stack trace.

### Conflict Detection

When two or more instances match the same goal, the resolution engine picks one based on declaration order, priority hints, or specificity — but the user often has no idea this happened. Claude identifies these ambiguous cases: which instances match, which one wins, and on what basis. This is especially valuable for library authors adding new instances who need to know whether their instance will shadow an existing one or be shadowed by it.

Given a specific instance and a goal, Claude can also explain why that particular instance was or was not selected — the unification details, prerequisite constraints, and priority ordering that determined the outcome.

## Design Rationale

### Why typeclass debugging is a top pain point

Typeclass resolution failures are consistently cited as one of the most frustrating aspects of working with Coq. The errors are opaque by default, the debugging tools require expert knowledge to use, and the output is voluminous and unstructured. Unlike proof failures — where the user at least sees a clear goal and can reason about tactics — typeclass errors offer almost no foothold. Users are left guessing, and guessing in a system with complex instance hierarchies is slow and error-prone.

### Why LLM interpretation of debug traces is the key value add

The underlying Coq commands are mature and reliable. The problem is not that the information is unavailable — it is that the information is presented in a form that requires significant expertise to interpret. An LLM that can read a verbose, deeply nested resolution trace and produce a two-sentence explanation of what went wrong provides exactly the translation layer that is missing. The development cost is low because no new Coq functionality is required; the value comes entirely from making existing output accessible through natural language. This is one of the highest-leverage applications of an LLM-powered tool: the machine does the tedious parsing and pattern-matching; the user gets the insight.

## Acceptance Criteria

### Instance Inspection

**Priority:** P0
**Stability:** Stable

- GIVEN a valid typeclass name WHEN instance listing is invoked THEN it returns all registered instances including instance name, type signature, and defining module
- GIVEN a typeclass with no registered instances WHEN instance listing is invoked THEN it returns an empty list with a clear indication that no instances exist
- GIVEN a name that is not a typeclass WHEN instance listing is invoked THEN it returns an informative error indicating the name does not refer to a typeclass

**Traces to:** R-TC-P0-1

### Typeclass Listing

**Priority:** P1
**Stability:** Stable

- GIVEN a Coq environment with loaded libraries WHEN typeclass listing is invoked THEN it returns all registered typeclasses with summary information
- GIVEN the typeclass list WHEN it is inspected THEN each entry includes at minimum the typeclass name and the number of registered instances

**Traces to:** R-TC-P1-4

### Resolution Tracing

**Priority:** P0
**Stability:** Stable

- GIVEN a proof state with an unresolved typeclass goal WHEN resolution tracing is invoked THEN it returns a structured trace showing which instances were tried, in what order, and whether each succeeded or failed
- GIVEN a resolution trace WHEN it is inspected THEN each step includes the instance name, the goal it was applied to, and the outcome (success, unification failure, or sub-goal failure)
- GIVEN the raw output of `Set Typeclasses Debug` WHEN it is processed THEN it is parsed into a structured representation rather than returned as raw text

**Traces to:** R-TC-P0-2, R-TC-P0-5

### Resolution Failure Explanation

**Priority:** P0
**Stability:** Stable

- GIVEN a resolution failure caused by no matching instance WHEN the explanation is returned THEN it states that no instance was found and identifies the specific typeclass and type arguments that lack an instance
- GIVEN a resolution failure caused by unification failure against a specific instance WHEN the explanation is returned THEN it identifies the instance and explains which type arguments failed to unify
- GIVEN a resolution failure caused by exceeding the maximum resolution depth WHEN the explanation is returned THEN it states that depth was exceeded and shows the resolution path that led to the loop or deep chain

**Traces to:** R-TC-P0-3

### Resolution Search Tree

**Priority:** P1
**Stability:** Draft

- GIVEN a goal requiring typeclass resolution WHEN the search tree is requested THEN it returns a tree structure showing each resolution step, branching points, and outcomes
- GIVEN a branching point in the search tree WHEN it is inspected THEN it shows all candidate instances at that point and indicates which was selected and why alternatives were rejected
- GIVEN a search tree WHEN it is presented THEN the depth and branching structure are clearly communicated (e.g., via indentation or explicit parent-child relationships)

**Traces to:** R-TC-P1-1

### Instance Conflict Detection

**Priority:** P1
**Stability:** Stable

- GIVEN a goal for which multiple instances match WHEN conflict detection is invoked THEN it identifies all matching instances and indicates which one resolution selects
- GIVEN conflicting instances WHEN the result is inspected THEN it explains the basis for selection (declaration order, priority hint, or specificity)
- GIVEN a single matching instance for a goal WHEN conflict detection is invoked THEN it confirms that resolution is unambiguous
- GIVEN a specific instance and a goal WHEN instance explanation is requested THEN it explains whether the instance matches the goal, and if so, with what unification
- GIVEN an instance that was not selected despite matching WHEN the explanation is returned THEN it identifies the instance that was selected instead and explains the priority or ordering reason
- GIVEN an instance that does not match the goal WHEN the explanation is returned THEN it identifies which type arguments or prerequisite constraints prevented matching

**Traces to:** R-TC-P1-2, R-TC-P1-3

### Typeclass Debugging MCP Tools

**Priority:** P0
**Stability:** Stable

- GIVEN a running MCP server WHEN its tool list is inspected THEN typeclass debugging tools are present with documented schemas
- GIVEN a typeclass debugging tool WHEN it is invoked with valid parameters THEN it returns structured results within 5 seconds for standard library-scale typeclass hierarchies
- GIVEN a typeclass debugging tool WHEN it is invoked with invalid parameters THEN it returns a clear error message indicating the problem

**Traces to:** R-TC-P0-4

### Resolution Fix Suggestions

**Priority:** P2
**Stability:** Draft

- GIVEN a resolution failure caused by a missing instance WHEN a fix suggestion is requested THEN it suggests adding an instance declaration with the appropriate type signature
- GIVEN a resolution failure caused by a missing import WHEN a fix suggestion is requested THEN it identifies the module that provides the needed instance and suggests importing it
- GIVEN a resolution failure with no straightforward fix WHEN a fix suggestion is requested THEN it explains why no simple fix is available and describes what would be needed

**Traces to:** R-TC-P2-1

### Instance Priority Issues

**Priority:** P2
**Stability:** Draft

- GIVEN a newly registered instance WHEN priority analysis is performed THEN it identifies any existing instances that the new instance would shadow for common goal patterns
- GIVEN a shadowing relationship WHEN it is reported THEN it includes the specific goal pattern affected and both the shadowing and shadowed instance names

**Traces to:** R-TC-P2-2
