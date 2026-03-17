Scan the entire Coq project for proof obligations (`admit`, `Admitted`, `Axiom` declarations), classify each by intent, rank by severity, and produce a structured summary report. This command is read-only — it never modifies source files.

## Step 1: Discover `.v` files

Use Glob with `**/*.v` to find all Coq source files in the project. If no `.v` files are found, report "No Coq source files found in this project" and stop.

## Step 2: Scan for obligations

Use Grep to search all `.v` files for the following patterns. Run these searches in parallel:

- `\badmit\b` — inline proof placeholders (tactic-level)
- `\bAdmitted\b` — sentence-level proof abandonment
- `\bAxiom\b` — axiom declarations

For each match, capture the file path, line number, and the matching line content. Use output_mode "content" with `-n` for line numbers and `-C 3` for surrounding context (3 lines before and after).

If no matches are found across all patterns, report "No proof obligations found — the project has no admits, Admitted proofs, or Axiom declarations" and stop.

## Step 3: Gather enclosing context for each obligation

For each detected obligation, determine what definition, lemma, theorem, or section it belongs to. Do this by:

1. Reading the file around the match (use Read with an appropriate line range) to identify the enclosing `Lemma`, `Theorem`, `Definition`, `Proposition`, `Corollary`, `Fact`, `Remark`, `Instance`, `Program`, or `Section` declaration.
2. For `Axiom` declarations, use `vernacular_query` with `Print Assumptions` on downstream theorems when feasible to understand dependency impact. For large projects, limit this to a representative sample rather than exhaustively querying every theorem.

## Step 4: Classify each obligation by intent

Assign one of three classifications to each obligation:

**Intentional Axiom** — The obligation is a deliberate foundational assumption. Signals:
- Surrounding comments explicitly state the assumption is intentional (e.g., "We assume classical logic", "This is an axiom of our system")
- The name follows a project convention for axioms (e.g., `Ax_`, `axiom_`, or placed in a module named `Axioms`, `Assumptions`, `Foundations`)
- The axiom states a well-known logical principle (e.g., functional extensionality, classical logic, UIP)
- The axiom appears in a dedicated axioms file or section

**TODO Placeholder** — The obligation is unfinished work someone intends to complete. Signals:
- Surrounding comments contain TODO, FIXME, HACK, XXX, "should prove", "need to prove", "later", "placeholder"
- The name contains `todo`, `stub`, `placeholder`, `temp`
- An `admit` or `Admitted` inside a `Lemma`/`Theorem` body with no comment justifying it
- An `Axiom` that states something provable (e.g., a concrete property of defined functions) rather than a foundational principle

**Unknown** — Insufficient context to determine intent. Use this when signals are ambiguous or absent. Do not guess — unknown is a valid and useful classification.

When in doubt, classify as Unknown rather than forcing a judgment.

## Step 5: Assign severity

Assign each obligation a severity level:

**High**
- TODO placeholder in a definition/theorem that other results depend on (high fan-out)
- Any `admit`/`Admitted` in a module that appears to be core infrastructure
- An Unknown obligation in a critical path (if dependency information is available)

**Medium**
- TODO placeholder in a standalone or leaf lemma with few or no dependents
- Unknown obligations with no dependency information
- An `Axiom` that looks like a TODO but has some ambiguity

**Low**
- Intentional axioms that are well-documented foundational assumptions
- `admit` in test files, examples, or scratch/playground files
- Obligations in files whose path suggests non-production code (e.g., `examples/`, `test/`, `scratch/`)

## Step 6: Check for filtering arguments

If the user passed arguments to the command, apply filters before producing output:
- A file or directory path: restrict results to obligations in that subtree
- `--severity high|medium|low`: show only obligations at that severity level
- `--classification axiom|todo|unknown`: show only obligations with that classification
- Multiple filters can be combined

## Step 7: Produce the report

Output a structured summary with the following sections:

### Overview

State the total count of obligations found, broken down by classification and severity. Example:

> Found **14 proof obligations** across 8 files: 3 intentional axioms, 9 TODO placeholders, 2 unknown.
> Severity breakdown: 4 high, 6 medium, 4 low.

### High Severity

List each high-severity obligation with:
- File path and line number
- Enclosing definition/theorem name
- The obligation type (`admit`, `Admitted`, or `Axiom`)
- Classification and reasoning (one sentence explaining why)
- Relevant surrounding context (the key line, not the full 3-line window)

### Medium Severity

Same format as High.

### Low Severity

Same format as High.

### Recommendations

After listing all obligations, provide 2-4 actionable recommendations. Focus on:
- Which high-severity TODOs to address first and why
- Whether any Unknown obligations deserve investigation
- Any patterns observed (e.g., "all admits are concentrated in `Sorting.v` — this file may need a focused proof effort")

## Edge cases

- **Large projects (>100 `.v` files):** Scan all files but keep `vernacular_query` calls targeted. Do not run `Print Assumptions` on every theorem — sample strategically. Prioritize classification accuracy over exhaustive dependency analysis.
- **Files with many obligations (>20 in one file):** Group them in the report rather than listing individually. Note the file as a hotspot.
- **Obligations inside comments:** Grep may match `admit` inside Coq comments `(* ... *)`. When reviewing context, discard matches that are clearly inside comments. Check for `(*` before the match on the same line or in preceding lines without a closing `*)`.
- **`Admitted` used as a name component:** Discard matches where `Admitted` appears as part of an identifier (e.g., `not_Admitted_here`). The word boundary in the regex should handle most cases, but verify from context.
- **Opaque/plugin axioms:** Some axioms are generated by plugins (e.g., `Extraction`, `Declare Module`). Note these as "generated" if identifiable, and classify as Intentional Axiom with low severity.
