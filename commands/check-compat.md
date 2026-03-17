Check whether a Coq project's declared dependencies are mutually compatible. Detect version conflicts before the user hits opaque build failures. Explain conflicts in plain language and suggest resolutions.

## Step 1: Locate and read dependency declarations

Search the project for dependency declaration files in this order:

1. Use Glob to find `*.opam` files in the project root and subdirectories.
2. Look for `dune-project` in the project root.
3. Look for `_CoqProject` in the project root.

Read every file found. Extract all declared dependencies and any version constraints from each file. opam files use `depends:` blocks. dune-project uses `(depends ...)` s-expressions. `_CoqProject` may reference packages via `-R` or `-Q` flags but rarely declares version constraints directly.

If no dependency declaration files are found, tell the user: "No opam file, dune-project, or _CoqProject found. There are no declared dependencies to analyze." Stop here.

If files are found but they declare no dependencies, tell the user: "Dependency files found but no dependencies are declared." Stop here.

Collect the full list of direct dependencies with their version constraints (if any) before proceeding.

## Step 2: Query opam for package metadata

For each direct dependency, run Bash commands to gather metadata:

```
opam show <package> --field=depends,conflicts,available,version
```

If opam is not available or the command fails, tell the user: "opam is not available in this environment. Cannot query package metadata for compatibility analysis." Fall back to reporting only what can be inferred from the project's own declaration files — flag any constraints that look potentially conflicting based on the declared version ranges alone, but note that full transitive analysis requires opam.

If a package name is not found in opam, flag it immediately: "<package> is not available in the configured opam repositories. Check spelling and ensure the correct opam repository is added."

For each package that exists, record:
- All available versions
- The `depends:` constraints for each relevant version
- The `conflicts:` field
- The `available:` field (often constrains OCaml or Coq versions)

Use `opam show <package> --field=depends --show-empty` for each relevant version if needed. To list available versions: `opam show <package> --field=all-versions`.

## Step 3: Build the constraint picture

From the metadata collected in Step 2, build a picture of the transitive dependency tree:

1. For each direct dependency, identify its own dependencies (transitive deps). Query opam for those as well, recursively, until the full tree is mapped. Keep this practical — go deep enough to find shared constraints (usually 2-3 levels), not infinitely deep.
2. Identify shared dependencies across the tree. The most common shared constraints are:
   - The Coq (or Rocq) version: nearly every Coq library constrains this
   - The OCaml version
   - Shared libraries like coq-mathcomp-ssreflect that multiple packages depend on
3. For each shared dependency, collect the version constraint that every depending package imposes on it.

## Step 4: Detect conflicts

For each shared dependency (especially the Coq version), check whether the intersection of all imposed constraints is non-empty:

- If the constraints have a non-empty intersection, the dependencies are compatible for that shared resource. Record the satisfying version range.
- If the constraints have an empty intersection, there is a conflict. Record exactly which packages impose which constraints.

Also check the `conflicts:` fields — if any declared dependency explicitly conflicts with another declared dependency, flag it.

Use `opam install --dry-run --show-actions <all-deps>` as a cross-check if opam is available. This leverages opam's solver without modifying anything. If the dry run succeeds, report the versions opam would install. If it fails, use the solver output alongside your own analysis to identify the conflict.

## Step 5: Check Coq/Rocq version compatibility

This is the single most important check. Determine:

1. What Coq or Rocq version the project currently uses (check `opam list coq --installed --short` or `coqc --version` via Bash).
2. What range of Coq versions each dependency supports.
3. Whether the currently installed Coq version falls within the compatible range for all dependencies.
4. If the user asked about a hypothetical Coq version (e.g., "are my deps compatible with Coq 8.19?"), check against that version instead.

If the installed Coq version is incompatible with one or more dependencies, flag this prominently — it is the most likely cause of build failures.

## Step 6: Explain conflicts in plain language

For every conflict detected, produce an explanation that a Coq user (not an opam expert) can understand. Follow this structure:

- **What conflicts:** Name the two (or more) packages that cannot coexist.
- **Why:** State the shared resource they disagree on and what each one requires. Example: "coq-mathcomp-ssreflect 2.1.0 requires Coq >= 8.18, but coq-iris 4.0.0 requires Coq < 8.18. No single Coq version satisfies both."
- **Chain:** If the conflict is transitive (not between direct dependencies but between their sub-dependencies), trace the chain. Example: "Your project depends on A, which depends on B, which requires Coq < 8.17. Your project also depends on C, which requires Coq >= 8.18."

Do not reproduce raw opam constraint syntax in the explanation. Translate it.

## Step 7: Suggest resolutions

For each conflict, suggest one or more resolution strategies. Consider:

1. **Version pinning:** Is there an older or newer version of one of the conflicting packages that resolves the conflict? Check available versions and their constraints. If so, suggest: "Pin <package> to version X.Y.Z, which supports Coq >= A and < B, resolving the conflict."
2. **Upgrading:** If a newer version of a package widens its Coq compatibility range, suggest upgrading.
3. **Downgrading:** If the user is on a very new Coq version and a key dependency has not caught up, suggest which Coq version would satisfy everything.
4. **Alternative packages:** If a package has a known alternative that serves the same purpose with different version constraints, mention it.
5. **Constraint relaxation:** If the project's own opam file over-constrains a dependency, suggest relaxing the constraint.

When multiple resolutions exist, list them with trade-offs so the user can choose. When no resolution exists within available package versions, say so directly.

## Step 8: Produce the summary report

End with a structured summary. Use this format:

### Compatibility Report

**Overall verdict:** Compatible | Incompatible

**Coq version:** [installed version] — [compatible with all deps | incompatible with: list]

**Compatible dependencies:**
- List each dependency pair or group confirmed compatible, with the satisfying version range

**Conflicts found:**
- For each conflict: the packages involved, a one-line explanation, and the suggested resolution

**Recommendations:**
- Prioritized list of actions the user should take, starting with the highest-impact fix

If everything is compatible, say so clearly and report the newest mutually compatible version of each dependency.

## Handling hypothetical queries

If the user asks something like "would adding coq-equations break anything?" or "are my deps compatible with Coq 8.19?", run the same analysis but include the hypothetical package or version in the constraint set. Make clear in the report that the analysis includes a hypothetical addition and does not reflect the current project files.

## General guidelines

- Always run `opam update` status checks but never run `opam update` itself — do not modify the user's opam state.
- Do not modify any project files. This command is read-only analysis.
- If a step fails or produces ambiguous results, say what you could not determine and why, rather than guessing.
- Prefer concrete version numbers over vague advice. "Pin coq-mathcomp-ssreflect to 2.0.0" is better than "try an older version."
- Keep the report concise. Detailed constraint traces go in the explanation section, not the summary.
