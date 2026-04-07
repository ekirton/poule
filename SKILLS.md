# Skills Reference

Skills are slash commands that combine multiple tools into a single workflow. Type a skill name in Claude Code and it handles the rest — searching, opening proof sessions, verifying results, and presenting what it found.

Unlike individual MCP tools (see [MCP.md](MCP.md)), skills are multi-step workflows — Claude reasons between steps, adapts strategy based on intermediate results, and coordinates tools that no single tool call can replace.

## Proof Development

### /formalize

Translate a natural-language theorem into a formal Coq statement and help build the proof interactively.

```
/formalize For all natural numbers, addition is commutative
```

Claude searches for relevant existing lemmas, proposes a formal `Lemma` or `Theorem` statement, type-checks it against your project, and guides you through building the proof — trying automation first, then manual tactics.

### /compress-proof

Find shorter or cleaner alternatives to an existing proof.

```
/compress-proof rev_involutive in src/Lists.v
```

Claude reads the proof, extracts the goal, tries multiple strategies (hammer, direct lemma search, tactic simplification), verifies each alternative closes the goal, and presents ranked options. The original proof is never modified unless you choose a replacement.

### /explain-proof

Step through a proof with plain-language explanations of each tactic, including mathematical intuition and proof state evolution.

```
/explain-proof Nat.add_comm
```

Claude opens a proof session, steps through each tactic, and explains what it does and why — connecting formal tactics to the underlying mathematical reasoning. Supports `--brief` and `--verbose` detail levels.

## Project Maintenance

### /proof-obligations

Scan a project for all `admit`, `Admitted`, and `Axiom` declarations; classify by intent (intentional axiom vs. TODO placeholder); rank by severity.

```
/proof-obligations
/proof-obligations src/Algebra/
```

### /proof-lint

Analyze proof scripts for deprecated tactics, inconsistent bullet style, and unnecessarily complex tactic chains.

```
/proof-lint src/Core.v
/proof-lint --fix
```

Claude detects style issues, reports them grouped by category, and optionally applies fixes — verifying each change through a proof session before committing it.

### /proof-repair

Systematically fix broken proofs after a Coq version upgrade.

```
/proof-repair
```

Claude builds the project, classifies each error (renamed lemma, deprecated tactic, type mismatch), applies targeted repair strategies, and iterates until the build succeeds or all fixable errors are resolved. Unfixable proofs are reported with diagnostics.

## Migration & Compatibility

### /migrate-rocq

Automated assistance with the Coq-to-Rocq namespace rename.

```
/migrate-rocq
```

Claude scans all `.v` and build files for deprecated `Coq.*` names, presents proposed replacements, applies bulk renames after confirmation, and verifies the build still passes. Offers rollback if the build breaks.

### /check-compat

Check whether your project's dependencies are mutually compatible before you hit opaque build failures.

```
/check-compat
```

Claude reads your opam/dune dependency declarations, analyzes version constraints for conflicts, and explains any incompatibilities in plain language with resolution suggestions.

## Education

### /textbook

Search the *Software Foundations* textbook for explanations of Coq concepts, tactics, and proof techniques.

```
/textbook how does induction work?
/textbook --volume lf rewrite tactic
```

Claude retrieves the most relevant passages with source citations and gives you local file paths so you can open chapters in your browser for extended reading.

## Error Diagnosis

### /explain-error

Parse a Coq type error and explain in plain language what went wrong, with context-aware fix suggestions.

```
/explain-error
```

Claude fetches the error (from your last build or conversation), looks up relevant type definitions and coercions, explains the root cause, and suggests concrete fixes. Handles type mismatches, unification failures, universe inconsistencies, missing coercions, and notation confusion.

## Scaffolding

### /scaffold

Generate a complete Coq/Rocq project skeleton with build files, CI configuration, and boilerplate.

```
/scaffold
```

Claude asks for project parameters (name, build system, Coq version, dependencies) and generates the full directory structure — dune-project, opam file, CI config, .gitignore, source boilerplate, and README. Verifies the generated project builds successfully.

---

## Summary

| Skill | What it does | How it runs |
|-------|-------------|-------------|
| `/formalize` | Natural language to formal theorem + proof | Interactive |
| `/compress-proof` | Find shorter proof alternatives | Automated |
| `/explain-proof` | Step-by-step proof explanation | Automated |
| `/proof-obligations` | Scan for admits/axioms, classify, rank | Automated |
| `/proof-lint` | Style linting with optional auto-fix | Automated |
| `/proof-repair` | Fix broken proofs after version upgrade | Automated, iterative |
| `/migrate-rocq` | Coq to Rocq namespace migration | Semi-automated |
| `/check-compat` | Dependency compatibility analysis | Automated |
| `/explain-error` | Type error explanation + fix suggestions | Automated |
| `/textbook` | Search Software Foundations | Automated |
| `/scaffold` | Project skeleton generation | Interactive |
