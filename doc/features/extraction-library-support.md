# Extraction Library Support

Which Coq libraries and projects the extraction pipeline supports, at what fidelity, and why the coverage tiers are structured as they are.

---

## Problem

Coq projects vary enormously in proof style, tactic usage, and build system complexity. The standard library uses basic Ltac tactics. MathComp uses ssreflect, a distinct tactic language with different proof state conventions. Industrial projects like Iris and CompCert define custom proof modes and domain-specific tactic frameworks. A single extraction approach will not work uniformly across all of these — and researchers need to know which projects will extract reliably before investing in extraction campaigns.

## Solution

Three tiers of library support, reflecting increasing extraction difficulty:

**Tier 0 (P0): Controlled, high-confidence**
- Coq standard library: ≥ 95% extraction success rate
- MathComp (boot, order, algebra, fingroup, solvable, field, character): ≥ 90% extraction success rate
- stdpp: ≥ 90% extraction success rate
- Flocq: ≥ 95% extraction success rate
- Coquelicot: ≥ 95% extraction success rate
- CoqInterval: ≥ 90% extraction success rate

The MathComp target includes the core component hierarchy: `rocq-mathcomp-boot` (ssreflect base), `rocq-mathcomp-order`, `rocq-mathcomp-algebra`, `rocq-mathcomp-fingroup`, `rocq-mathcomp-solvable`, `rocq-mathcomp-field`, and `rocq-mathcomp-character`. The compatibility meta-package `rocq-mathcomp-ssreflect` wraps `rocq-mathcomp-boot` and `rocq-mathcomp-order`; version detection queries this meta-package. Together these packages provide the ssreflect, order theory, algebra, group theory, and finite field libraries that constitute "MathComp" as referenced elsewhere in this document.

**Tier 1 (P1): Validated opam-installable projects**
- Standard-Ltac projects beyond the Tier 0 set: validated extraction, success rate reported
- ssreflect-based projects (e.g., MathComp satellites): validated extraction, success rate reported
- The extraction tool accepts arbitrary opam-installable projects; Tier 1 projects are those where extraction has been validated

**Tier 2 (P2): Framework-heavy projects**
- Projects using custom proof modes (e.g., Iris iProofMode) or domain-specific tactic frameworks (e.g., CompCert decision procedures)
- Extraction proceeds with best-effort premise annotations — reduced granularity where custom tactics wrap standard Coq tactics
- These projects represent Coq's unique value for training data (no Lean equivalents exist), but their custom proof infrastructure makes full-fidelity extraction significantly harder

## Design Rationale

### Why tiered coverage rather than uniform targets

MathComp's ssreflect tactics interact with proof states differently than standard Ltac — goals are transformed through view application, rewriting chains, and case analysis combinators rather than discrete `apply`/`rewrite` steps. Requiring 95% coverage on MathComp from day one would block delivery of the standard library pipeline. The 90% target for MathComp acknowledges that ssreflect proofs are extractable but some edge cases (deeply chained views, custom canonical structure resolution) may require iterative improvement.

### Why these six libraries as Tier 0

These two libraries provide the largest volume of high-quality proofs with the most predictable tactic usage. The standard library covers foundational mathematics (arithmetic, logic, lists, sets). MathComp covers algebra, group theory, and combinatorics. Together they provide a diverse training corpus while remaining within well-understood tactic dialects. They are also the libraries most Coq projects depend on, so their theorems appear as premises in downstream proofs. The four additional libraries (stdpp, Flocq, Coquelicot, CoqInterval) are all standard-Ltac compatible, actively maintained, in the Rocq Platform, and extractable without special processing. They form coherent dependency chains — the numerical analysis stack (Flocq, Coquelicot, CoqInterval) and the general-purpose extension (stdpp) — and are widely used as foundations for downstream projects.

### Why Tier 2 accepts reduced premise granularity

Custom proof modes like Iris's iProofMode define tactics (e.g., `iIntros`, `iApply`) that internally invoke sequences of standard Coq tactics. Annotating premises at the custom-tactic level rather than the underlying Coq-tactic level loses some granularity but still provides useful training signal — the researcher knows that `iApply "H"` used hypothesis H, even if the internal rewriting steps are not individually annotated. Demanding full granularity would require deep integration with each framework's internals, which is not scalable.

### Why these projects matter despite extraction difficulty

CompCert (verified C compiler), Fiat-Crypto (cryptographic primitives), and Iris (concurrent separation logic) represent proof domains with no Lean equivalent. AI models trained only on Lean data cannot handle the reasoning patterns in these domains. Even partial extraction from these projects provides training signal that is otherwise unobtainable.

## Scope Boundaries

Extraction library support provides:

- Tiered coverage targets with explicit success rate thresholds
- Validated extraction for standard-Ltac and ssreflect-based projects
- Best-effort extraction with reduced premise granularity for custom proof modes

It does **not** provide:

- Guaranteed success rates for arbitrary projects (only Tier 0 has firm targets)
- Automatic detection of proof mode type or tactic framework
- Framework-specific extraction plugins or adapters
- Cross-language extraction (Lean, Isabelle)

## Acceptance Criteria

### Coq Standard Library Extraction

**Priority:** P0
**Stability:** Stable

- GIVEN the Coq standard library WHEN extraction is run THEN ≥ 95% of provable theorems produce successful proof trace records
- GIVEN the extraction output WHEN theorem names are inspected THEN they are fully qualified and match the standard library's module structure
- GIVEN the Coq standard library WHEN extraction is run on a single machine without GPU THEN extraction completes in under 1 hour

**Traces to:** R3-P0-7

### MathComp Extraction

**Priority:** P0
**Stability:** Stable

- GIVEN the MathComp library WHEN extraction is run THEN ≥ 90% of provable theorems produce successful proof trace records
- GIVEN MathComp proofs that use ssreflect tactics WHEN they are extracted THEN the per-step tactic text and proof states are correctly captured

**Traces to:** R3-P0-8

### Arbitrary Opam-Installable Projects

**Priority:** P1
**Stability:** Stable

- GIVEN an opam-installable Coq project that builds successfully WHEN extraction is run THEN proof traces are produced for provable theorems in that project
- GIVEN at least two standard-Ltac projects (e.g., Flocq, stdpp) WHEN extraction is run THEN proof traces are successfully produced
- GIVEN at least two ssreflect-based projects (e.g., MathComp satellites) WHEN extraction is run THEN proof traces are successfully produced

**Traces to:** R3-P1-7

### Custom Proof Mode Support

**Priority:** P2
**Stability:** Draft

- GIVEN a project using custom proof modes (e.g., Iris iProofMode) WHEN extraction is run THEN proof traces are produced with best-effort premise annotations
- GIVEN a custom tactic that wraps standard Coq tactics WHEN extraction encounters it THEN the output accepts reduced premise annotation granularity rather than failing

**Traces to:** R3-P2-1
