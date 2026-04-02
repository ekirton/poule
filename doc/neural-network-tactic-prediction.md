# Tactic Prediction from Proof States

## Status

**Active development.** Replaces the abandoned neural premise selection approach (see [neural-network-search.md](neural-network-search.md) for why that failed). The extraction pipeline captures 140,358 (proof_state, tactic) steps across 136,936 unique states — 40x more training data than was available for premise retrieval.

## Problem

The original neural training pipeline trained a bi-encoder to retrieve *premises* given a proof state. This required (proof_state, premises_used) pairs, but Coq's kernel does not track which lemmas each tactic consults. The result: the extraction pipeline captures proof records but only ~3,500 produce non-empty premise lists usable as training pairs — a 97% attrition rate.

However, the extraction pipeline *does* capture the tactic text at each step (`ExtractionStep.tactic`). Every goal state has the tactic that was applied to it, regardless of whether that tactic's premises are known. This represents a 40× larger training signal.

| Training signal | Available pairs | Source |
|----------------|----------------|--------|
| Premise retrieval (old) | ~3,500 | Steps with non-empty `premises` |
| Tactic prediction (current) | 140,358 | All steps with `tactic` text |

## What is Tactic Prediction

Given a proof state (goal type + hypotheses), predict the next tactic the user should apply. This is a sequence generation or classification task, depending on how it is framed:

- **Classification**: Predict the tactic *family* (e.g., `apply`, `rewrite`, `induction`, `auto`, `simpl`). Simpler to train, useful for suggesting a short list of likely tactics.
- **Generation**: Predict the full tactic text including arguments (e.g., `rewrite IHn`, `apply Nat.add_comm`). More useful but requires a generative model or a retrieval + template approach.
- **Hybrid**: Predict the tactic family, then retrieve argument candidates from the proof context and accessible lemma set. This is closest to what Tactician and CoqHammer do.

## Prior Art

| System | Approach | Training data | Results |
|--------|----------|--------------|---------|
| Tactician (Blaauwbroek et al., 2020) | k-NN on proof states → tactic | Coq stdlib + 120 packages | 39% of Coq theorems proved |
| CoqHammer (Czajka & Kaliszyk, 2018) | ATP premise selection + reconstruction | Coq stdlib | ~40% automation rate |
| Proverbot9001 (Sanchez-Stern et al., 2020) | RNN tactic prediction | Coq CompCert | 48% of theorems in 10 minutes |
| GPT-f (Polu & Sutskever, 2020) | Transformer tactic generation | Lean Mathlib | 56.5% on miniF2F |
| HTPS (Lample et al., 2022) | Hyper-tree proof search + tactic gen | Lean/Metamath | 82.6% on miniF2F |
| ReProver (Yang et al., 2023) | Retrieval-augmented tactic generation | Lean Mathlib (LeanDojo) | 51.2% on LeanDojo benchmark |

The common thread: tactic prediction works well even without per-step premise annotations, because the model learns tactic patterns from the proof state structure alone.

## Proposed Approach

### Phase 1: Emit tactic labels in extraction output (done)

The extraction pipeline emits JSONL training data with (proof_state, tactic) pairs. Validation of the current training corpus:

| Metric | Value |
|--------|-------|
| Total steps | 140,358 |
| Unique states | 136,936 |
| Missing tactic | 0 |
| Malformed records | 0 |
| Tactic families | 2,113 |

Top tactic families by frequency:

| Family | Count | % |
|--------|------:|--:|
| `rewrite` | 26,950 | 19.2% |
| `apply` | 24,562 | 17.5% |
| `intros` | 10,702 | 7.6% |
| `auto` | 5,692 | 4.1% |
| `unfold` | 5,232 | 3.7% |
| `have` | 4,184 | 3.0% |
| `move=>` | 3,890 | 2.8% |
| `case` | 3,834 | 2.7% |
| `destruct` | 3,831 | 2.7% |
| `-` | 3,240 | 2.3% |
| `{` | 2,869 | 2.0% |
| `assert` | 2,808 | 2.0% |
| `exists` | 2,368 | 1.7% |
| `elim` | 2,172 | 1.5% |
| `exact` | 2,168 | 1.5% |
| `replace` | 2,093 | 1.5% |
| `simpl` | 1,941 | 1.4% |
| `split` | 1,873 | 1.3% |
| `move` | 1,616 | 1.2% |
| `+` | 1,357 | 1.0% |

The top 20 families cover ~80% of all steps. However, 2,011 families have fewer than 50 examples — these rare families will need grouping or exclusion during training.

### Phase 2: Tactic family classifier

Train a classifier on (proof_state → tactic_family) using a custom tokenizer and encoder:

1. Tokenize the proof state using a Coq-specific vocabulary (see below)
2. Encode via transformer encoder (mean pooling)
3. Add a classification head mapping to the top-K tactic families
4. Train with cross-entropy loss on 140K (state, tactic_family) pairs

#### Vocabulary

A Coq-specific vocabulary has been built from the index and training data:

| Component | Tokens |
|-----------|-------:|
| Special tokens (`[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]`) | 5 |
| Fixed tokens (punctuation, operators, scope annotations, Unicode symbols, Coq keywords) | 111 |
| Index declarations (all 6 libraries) | 118,363 |
| Training data tokens (from proof states) | 39,895 |
| **Total vocabulary** | **158,374** |

This domain-specific tokenizer avoids sub-word fragmentation of Coq identifiers — every declaration in the index and every token observed in training data gets a single vocabulary entry.

### Phase 3: Tactic argument retrieval

For tactics that take lemma arguments (`apply`, `rewrite`, `exact`), combine the tactic family prediction with premise retrieval:

1. Predict tactic family from Phase 2
2. If the predicted tactic takes a lemma argument, run the existing premise retrieval pipeline to suggest candidates
3. Construct full tactic suggestions: `apply <candidate>`, `rewrite <candidate>`, etc.

This reuses the existing bi-encoder for premise retrieval but gates it behind tactic prediction, making the system more useful as a proof assistant.

### Phase 4: Integration as MCP tool

Expose tactic prediction as a new MCP tool `suggest_tactics` that takes a proof state and returns ranked tactic suggestions. This integrates directly into the existing proof session workflow.

## Advantages Over Current Approach

1. **40× more training data**: 140K tactic-labeled states vs. ~3,500 premise pairs, from the same extraction output.
2. **No kernel changes needed**: The tactic text is already captured by the extraction pipeline. Only the output format needs updating.
3. **Complements premise retrieval**: Tactic prediction and premise retrieval are orthogonal — tactic prediction selects the *verb*, premise retrieval selects the *noun*. They can be combined.
4. **Directly useful**: "You should try `induction n`" is more actionable than "these lemmas are relevant." Users of the MCP proof session tools would benefit immediately.
5. **Established approach**: Tactician, Proverbot9001, and CoqHammer all demonstrate that tactic prediction works for Coq without per-step premise tracking.

## Challenges

### Tactic text normalization

Coq tactics have complex syntax with arguments, combinators (`;`, `||`), and SSReflect extensions. The tactic text needs normalization before it can be used as a training label:
- Strip comments and whitespace
- Normalize SSReflect compound tactics (e.g., `move=> /eqP ->` is one step)
- Handle tactic arguments that include proof terms (e.g., `refine (ex_intro _ _ _)`)

### Class imbalance

Some tactics (`rewrite` at 19.2%, `apply` at 17.5%) dominate the distribution while 2,011 of 2,113 families have fewer than 50 examples. The classifier needs class weighting or focal loss to avoid degenerate predictions, and rare families should be grouped or excluded.

### SSReflect proofs

MathComp uses SSReflect's tactic language extensively. SSReflect compound tactics (e.g., `rewrite !addnA addnC`) pack multiple operations into a single step, making tactic family classification harder. These may need special handling or a separate SSReflect-aware head.

### Evaluation

Tactic prediction accuracy is not the same as proof completion rate. The model may predict the correct tactic family 80% of the time but still fail to produce a complete proof because the argument is wrong. Evaluation should track:
- Top-1 and top-5 tactic family accuracy
- Full tactic accuracy (exact match after normalization)
- Proof closure rate (can the predicted tactic close the current goal when executed?)

## Implementation Scope

| Phase | Effort | Status |
|-------|--------|--------|
| Phase 1: Emit tactic records | Small | **Done** — 140K steps extracted, validated |
| Phase 2: Tactic classifier | Medium | **In progress** — vocabulary built (158K tokens) |
| Phase 3: Argument retrieval | Medium | Blocked on Phase 2 |
| Phase 4: MCP integration | Small | Blocked on Phase 2 or 3 |

## Relationship to Other Work

- **Complements**: premise retrieval (tactic prediction selects the verb, retrieval selects the noun)
- **Supersedes**: cross-prover transfer training (uses existing Coq data instead of requiring Lean datasets)
- **Enables**: proof search / auto-completion in the MCP proof session tools
- **Blocked by**: nothing — extraction data (140K steps) and vocabulary (158K tokens) are ready
