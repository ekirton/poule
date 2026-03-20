# User Stories: Auto/Eauto Trace Explanation

Derived from [doc/requirements/auto-trace-explanation.md](../auto-trace-explanation.md).

---

## Epic 1: Diagnose a Failed Auto/Eauto Invocation

### 1.1 Explain Why Auto Failed

**As a** Coq developer whose `auto` call did not solve the goal,
**I want to** ask Claude why `auto` failed and see which hints were tried,
**so that** I can fix the issue without manually running `debug auto` and interpreting its raw output.

**Priority:** P0
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active proof session with an open goal WHEN the user asks why `auto` failed THEN the tool runs `auto` with debug tracing, parses the output, and returns a structured report listing each hint that was considered, attempted, or filtered
- GIVEN a goal where `auto` fails because the relevant hint is registered in a database not consulted by default WHEN the diagnosis is requested THEN the report identifies the database gap and suggests `auto with <db>`
- GIVEN a goal where `auto` fails because the default depth (5) is insufficient WHEN the diagnosis is requested THEN the report states the minimum depth required and suggests `auto <N>`
- GIVEN a goal where `auto` fails but `eauto` would succeed (because a hint leaves existential variables) WHEN the diagnosis is requested THEN the report explicitly states that `eauto` would succeed and explains the evar distinction
- GIVEN a goal where no hints in scope match the head symbol WHEN the diagnosis is requested THEN the report explains the head symbol filtering and suggests alternative tactics or manual `apply`

**Traces to:** AT-P0-1, AT-P0-2, AT-P0-3, AT-P0-4, AT-P0-5, AT-P0-6, AT-P0-7

### 1.2 Explain Why a Specific Hint Was Not Used

**As a** Coq developer who registered a hint and expects `auto` to use it,
**I want to** ask Claude specifically why that hint was not applied to my goal,
**so that** I can fix the registration, the goal shape, or my choice of tactic.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active proof session, a goal, and the name of a lemma registered as a hint WHEN the user asks why that specific hint was not used by `auto` THEN the tool returns a focused explanation of the rejection reason for that specific hint
- GIVEN a hint registered via `Hint Resolve` whose `simple apply` unification fails but whose full `apply` succeeds WHEN the diagnosis is requested THEN the report explains the weaker unification used by `auto` and suggests `eapply` or explicit instantiation
- GIVEN a hint registered in database `mydb` but `auto` invoked without `with mydb` WHEN the diagnosis is requested THEN the report identifies the database mismatch
- GIVEN a hint whose conclusion has a universally quantified variable not appearing in the goal's conclusion WHEN the diagnosis is requested THEN the report explains that `auto` cannot instantiate such variables and suggests `eauto`

**Traces to:** AT-P1-1

---

## Epic 2: Understand Successful but Unexpected Auto Behavior

### 2.1 Explain Which Proof Path Auto Chose

**As a** Coq developer whose `auto` solved the goal but used a different proof than expected,
**I want to** see the proof path that `auto` actually took and understand why my preferred lemma was not used,
**so that** I can control proof dependencies and ensure the right lemma is applied.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active proof session where `auto` succeeds WHEN the user asks which path `auto` took THEN the tool returns the winning tactic sequence (as `info_auto` would) along with an explanation of why each step was selected
- GIVEN a goal where `auto` chose hint A over the user's expected hint B WHEN the user asks why B was not preferred THEN the report explains the ordering: priority, cost, database order, or definition order
- GIVEN a goal where `auto` succeeds with a suboptimal proof (e.g., longer path, unnecessary axiom) WHEN the user asks for alternatives THEN the report identifies whether other hint paths existed and why they ranked lower

**Traces to:** AT-P1-2

---

## Epic 3: Compare Auto Variants on the Same Goal

### 3.1 Distinguish Auto, Eauto, and Typeclasses Eauto

**As a** Coq developer unsure which automation tactic to use,
**I want to** see how `auto`, `eauto`, and `typeclasses eauto` each behave on my current goal,
**so that** I can choose the right variant and understand the trade-offs.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active proof session with an open goal WHEN the user asks Claude to compare automation variants THEN the tool runs each variant against the goal and reports: which succeeded, which failed, and the key behavioral differences that explain the divergence
- GIVEN a goal where `auto` fails but `eauto` succeeds WHEN the comparison is requested THEN the report identifies the specific hint that required evar instantiation and explains why `auto` rejected it
- GIVEN a goal where `typeclasses eauto` succeeds but `eauto` fails WHEN the comparison is requested THEN the report explains the different databases consulted (`typeclass_instances` vs. `core`) and any Hint Mode constraints that affected resolution
- GIVEN a goal where all three fail WHEN the comparison is requested THEN the report provides a unified diagnosis covering the union of attempted hints and their failure reasons, with a suggestion for an alternative approach

**Traces to:** AT-P1-3

### 3.2 Show Effective Databases and Transparency Settings

**As an** advanced Coq developer debugging a subtle hint failure,
**I want to** see which databases and transparency settings were in effect for a failed `auto`/`eauto` call,
**so that** I can verify that my hints are registered where I think they are with the opacity I expect.

**Priority:** P1
**Stability:** Stable

**Acceptance criteria:**
- GIVEN an active proof session and a failed `auto` or `eauto` invocation WHEN the user asks to see the effective configuration THEN the tool lists: the databases consulted (in order), the transparency setting for each database, and any Hint Mode constraints in effect
- GIVEN a database created implicitly (via `Create HintDb` without transparency argument) WHEN the effective settings are shown THEN the report notes that the database defaults to opaque transparency and explains the implication for unification
- GIVEN `auto using foo` vs. `Hint Resolve foo` + `auto` WHEN the user encounters different behavior between the two THEN the report explains the known unification path inconsistency and recommends a workaround

**Traces to:** AT-P1-4, AT-P1-5

---

## Epic 4: Hint Search Visualization and Linting

### 4.1 Visualize the Hint Search Tree

**As a** Coq developer working with complex hint databases,
**I want to** see the hint search tree as a visual diagram,
**so that** I can understand the branching, backtracking, and failure points at a glance rather than reading a linear trace.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN an active proof session and a failed or succeeded `auto`/`eauto` invocation WHEN visualization is requested THEN the tool generates a tree diagram showing each hint application attempt as a node, with edges labeled by tactic, and failure reasons annotated on rejected branches
- GIVEN a search tree with more than 50 nodes WHEN visualization is requested THEN the diagram is pruned to show the most relevant branches (winning path if succeeded, deepest failed paths if failed) with a summary of elided branches
- GIVEN a visualization request THEN the diagram is written to `proof-diagram.html` following the same convention as existing Poule visualization tools

**Traces to:** AT-P2-1

### 4.2 Lint a Hint Database

**As an** advanced Coq developer maintaining a large hint database,
**I want to** scan a hint database for potential misconfigurations,
**so that** I can prevent `auto`/`eauto` failures before they occur during proof development.

**Priority:** P2
**Stability:** Draft

**Acceptance criteria:**
- GIVEN a hint database name WHEN the lint tool is invoked THEN it reports: hints with transparency mismatches (registered in an opaque database but requiring transparent unification), hints that shadow other hints due to identical patterns with different priorities, and Hint Extern patterns that are unreachable because a Hint Resolve with lower cost matches first
- GIVEN a project with multiple custom hint databases WHEN linting is requested without specifying a database THEN the tool lints all non-default databases and reports cross-database issues (hints registered in a database that no `auto with` invocation ever consults)
- GIVEN a lint report with no issues found THEN the tool confirms the database is clean rather than producing an empty result

**Traces to:** AT-P2-3, AT-P2-4
