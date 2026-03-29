# Proposal: Replace coq-lsp with coqtop for Proof Extraction

## Status

Future proposal — not scheduled for implementation.

## Motivation

Neural premise selection models learn to predict which library lemmas are useful for a given proof goal. Training requires pairs of `(proof_state, premises_used_by_this_tactic)` — typically 1-5 premises per step. The quality of these pairs determines model quality.

Lean's AI tooling lead is built on LeanDojo's ability to extract per-step premise annotations from the kernel. LeanHammer achieves 72.7% Recall@32 (vs. 38.7% for ReProver) primarily because of richer ground truth extraction — not a bigger model. Coq has no equivalent infrastructure.

The key technique is **proof term diffing**: Coq's kernel builds a partial proof term at each tactic step containing `Const` nodes for every referenced constant. By diffing constants before and after a tactic, we get exactly which constants that tactic introduced — ground truth for training. This captures everything: explicit references (`apply X`), implicit references from automation (`auto`, `simp`, `ring`), and term-style proof fragments.

| System | Premise source | Recall@32 |
|--------|---------------|-----------|
| ReProver (Lean) | Tactic text parsing only | 38.7% |
| LeanHammer (Lean) | Kernel premise resolution | 72.7% |
| CoqHammer (Coq) | Symbol overlap heuristic | ~42% |
| Poule (Coq, target) | Proof term diffing | 60%+ |

## Problem

The proof extraction pipeline depends on coq-lsp's Petanque API for three capabilities: proof state observation (`petanque/goals`), tactic replay (`petanque/run`), and tactic boundary detection (`coq/getDocument`). A separate coqtop subprocess (`ProofTermResolver` in `session/premise_resolution.py`) handles per-step premise resolution via `Show Proof.` diffing — the critical feature coq-lsp never provided.

coq-lsp is no longer maintained. Continuing to depend on it means:

- No bug fixes or Coq version compatibility updates.
- Two Coq processes per file (coq-lsp + coqtop), doubling memory.
- The Petanque API is frozen — the `petanque/proof` endpoint we needed will never ship.
- The LSP JSON-RPC protocol adds complexity (Content-Length framing, notification handling, document lifecycle) that a REPL does not require.

coqtop is maintained as part of Coq/Rocq itself and will continue to track Coq releases.

### Why not other alternatives?

| Alternative | Why insufficient |
|-------------|-----------------|
| `petanque/premises` (existing coq-lsp endpoint) | Returns ~16K accessible premises per step, not the 1-5 actually used |
| Tactic text parsing | Only handles explicit tactics (`apply X`); misses automation (`auto`, `simp`, `ring`) — exactly the steps where premise discovery matters most |
| SerAPI | Version-locked to specific Coq releases; unmaintained; heavyweight dependency |
| `.vo` file analysis | No public API for proof term extraction from compiled files |
| Post-Qed `Print` command | Gives per-proof premises (whole proof), not per-step — much noisier training signal |
| Pure static analysis of `.v` source | Cannot compute proof states or premise resolution — requires Coq's type checker and tactic interpreter |

## Proposed Approach

Replace coq-lsp with a single coqtop-based `CoqBackend` implementation. This unifies the two existing Coq process paths (coq-lsp for state observation, coqtop for premise resolution) into one.

### Phase 1: Goal state parsing (~1 week)

**Goal**: Parse coqtop's proof state output into `ProofState`, `Goal`, and `Hypothesis` types.

coqtop's `Show.` command prints:

```
1 goal

  n, m : nat
  IHn : n + 0 = n
  ============================
  S n + 0 = S n
```

The structure is:
- Header line: `N goal(s)` or `No more goals.`
- Per goal: hypothesis block (indented `name[, name...] : type` lines), separator (`====...`), goal type
- Multiple goals separated by blank lines

**Work items**:

1. Write a `parse_coqtop_goals(text: str) -> list[Goal]` function that handles:
   - Single and multiple goals
   - Multi-line hypothesis types (continuation lines are indented further)
   - `let`-bound hypotheses (`name := body : type`)
   - Hypotheses with multiple names (`n, m : nat`)
   - Unicode and notation in types
   - `No more goals.` (proof complete)

2. Test against representative outputs from Software Foundations proofs covering: simple arithmetic, induction, case analysis, ssreflect-style, and multi-goal states.

3. Use `Set Printing All` to get fully qualified names (consistent with premise resolution), but parse both modes since `Set Printing All` output is harder to read for the serialized training state. Decision point: do we serialize with or without `Printing All`? The current pipeline serializes goals as coq-lsp returns them (with notations). We may want two queries per step: one with `Printing All` for premise extraction, one without for the training state text.

**Key files**: New module `src/Poule/session/coqtop_parser.py`. Tests in `test/unit/test_coqtop_parser.py`.

### Phase 2: Tactic segmentation (~3-5 days)

**Goal**: Extract tactic boundaries from .v source files without coq-lsp's document model.

The spec (`coq-proof-backend.md` section 4.1, `original_script` attribute) already defines a regex fallback for when `coq/getDocument` is unavailable. This becomes the primary path.

**Work items**:

1. Promote the regex sentence splitter from fallback to primary implementation. The existing `_PROOF_START_RE` in `premise_resolution.py` locates proof boundaries; extend it to split the proof body into sentences.

2. Handle known hard cases:
   - **Bullet markers** (`-`, `+`, `*`, `--`, `++`, `**`): These are separate sentences. Split before each bullet at line start.
   - **Braces** (`{`, `}`): Each brace is its own sentence.
   - **Periods inside comments** (`(* ... *)`): Strip comments before splitting.
   - **Periods inside strings** (`"..."`): Skip string literals.
   - **ssreflect tactic chains** (`move=> /eqP H; rewrite H.`): The period ends the chain; semicolons are internal. This parses correctly with a simple period-based split.
   - **Numeric literals** (`1`, `2.5`): Not a concern — Coq tactic-mode periods are always followed by whitespace or EOF.

3. Quantify accuracy: Run the splitter on all Software Foundations .v files and compare against coq-lsp's `coq/getDocument` output (captured once while coq-lsp still works) to measure disagreement rate. Target: <5% of proofs have any boundary disagreement.

4. Optionally, use `.glob` files as a secondary source. `.glob` files record character ranges for each sentence — they are produced by `coqc` during compilation and are always available for compiled libraries. This would give exact boundaries without coq-lsp, though the `.glob` format is undocumented and version-dependent.

**Key files**: New module `src/Poule/extraction/tactic_splitter.py`. Tests in `test/unit/test_tactic_splitter.py`.

### Phase 3: Unified coqtop backend (~3-5 days)

**Goal**: Implement `CoqBackend` protocol using coqtop only.

**Work items**:

1. Create `src/Poule/session/coqtop_backend.py` implementing the `CoqBackend` protocol defined in `specification/coq-proof-backend.md`:
   - `load_file(path)`: Send file prelude to coqtop (reuse `_extract_prelude_up_to_proof` from `premise_resolution.py`).
   - `position_at_proof(name)`: Send theorem statement + `Proof.`, query `Show.` for initial state. Store the original tactic script from the splitter.
   - `original_script`: Return tactics from Phase 2 splitter.
   - `execute_tactic(tactic)`: Send tactic, parse response for errors.
   - `get_proof_state()`: Send `Show.`, parse with Phase 1 parser.
   - `get_proof_term()`: Send `Show Proof.`, return raw text (reuse from `ProofTermResolver`).
   - `undo()`: Send `Undo.` (coqtop supports this natively).
   - `get_premises()`: Diff proof terms (reuse `extract_constants_from_proof_term`).
   - `shutdown()`: Kill subprocess.

2. Adapt the subprocess management from `ProofTermResolver`:
   - Sentinel-based output framing (already proven to work).
   - Timeout handling via `asyncio.wait_for`.
   - Load path configuration via `-R` and `-Q` flags.

3. Handle the sequential state model. coq-lsp's Petanque API allows random access to any state token. coqtop is sequential — you must replay from the beginning to reach step N. The current pipeline already replays the full script during `position_at_proof` and caches state tokens. For coqtop, cache the goal text and proof term text at each step during the initial replay instead of caching opaque tokens. This means `extract_trace` reads from cache rather than querying coqtop again.

4. Remove the dual-process model. Today, `campaign.py` spawns one coq-lsp backend and one `ProofTermResolver` per file. The new backend does both, halving memory use.

**Key files**: `src/Poule/session/coqtop_backend.py`, modifications to `src/Poule/session/backend.py` (or replace it).

### Phase 4: Campaign integration and testing (~3-5 days)

**Goal**: Wire the new backend into the extraction campaign and validate end-to-end.

**Work items**:

1. Update `campaign.py` to use the coqtop backend factory instead of the coq-lsp factory. The `backend_factory` parameter is already a callable — swap the implementation.

2. Update `create_coq_backend` factory in the spec to default to coqtop. Optionally retain coq-lsp as a secondary option behind a flag for transition period.

3. Run end-to-end extraction on:
   - `examples/` directory (13 compiled .v files with .vo and .glob).
   - Software Foundations `lf/` (Basics, Induction, Lists — representative variety).
   - One large library (e.g., Coq Stdlib Init) to validate memory behavior.

4. Compare output against a reference extraction (captured with coq-lsp while it still works):
   - Proof states: text should be semantically equivalent (may differ in whitespace/notation).
   - Premises: should match exactly (both use `Show Proof.` diffing).
   - Tactic boundaries: quantify and document any disagreements.

5. Run the neural training pipeline (`data.py` pair extraction, vocabulary building) on the new extraction output. Verify training pairs and vocabulary sizes are comparable.

6. Remove coq-lsp dependencies:
   - `src/Poule/extraction/backends/coqlsp_backend.py`
   - `src/Poule/session/backend.py` (coq-lsp-specific code)
   - LSP JSON-RPC protocol handling
   - Any coq-lsp version detection or compatibility code

**Key files**: `src/Poule/extraction/campaign.py`, `src/Poule/cli/commands.py` (CLI flags), test files.

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Goal state parsing breaks on unusual Coq output | Medium | Medium | Extensive test fixtures; fallback to raw text serialization |
| Tactic splitting misparses >5% of proofs | Low | Medium | Use .glob files as authoritative source; capture coq-lsp reference output now |
| coqtop sequential model is too slow for large libraries | Low | High | Cache all states during initial replay; parallelize across files (already done) |
| coqtop output format changes across Coq versions | Medium | Medium | Version detection (already in extraction spec); version-specific parse rules |
| `Show Proof.` output too large for complex proofs | Low | Low | Already handled — truncation + constant extraction works on partial output |

## Decision Points

1. **Printing mode for training states**: Serialize goal states with notations (human-readable, matches current pipeline) or with `Set Printing All` (fully qualified, machine-friendly)? Recommendation: notations for training state text, `Printing All` only for premise extraction. This requires two `Show.` queries per step.

2. **Tactic boundaries**: Regex splitter vs. .glob files? Recommendation: start with regex, measure accuracy, add .glob as a follow-up if accuracy is below 95%.

3. **Transition strategy**: Big-bang replacement or parallel backends? Recommendation: implement coqtop backend behind a `--backend=coqtop` flag, validate, then make it the default and remove coq-lsp code.

4. **ProofTermResolver consolidation**: Merge into the new backend or keep separate? Recommendation: merge — the whole point is eliminating the second process.

## What This Enables

- **No external dependency** beyond Coq/Rocq itself for proof extraction.
- **Half the memory** per file (one process instead of two).
- **Proof term access** at every step — the feature we requested from coq-lsp — for free.
- **Simpler protocol**: stdin/stdout REPL vs. LSP JSON-RPC with Content-Length framing.
- **Forward compatibility**: coqtop tracks Coq releases automatically.
