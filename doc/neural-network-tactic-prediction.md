# Proposal: Tactic Prediction from Proof States

## Status

Future proposal — not yet scheduled. This is a higher-priority alternative to cross-prover transfer training because it uses data we already extract (~105K goal states) rather than requiring external datasets or kernel changes.

## Problem

Our current neural training pipeline trains a bi-encoder to retrieve *premises* given a proof state. This requires (proof_state, premises_used) pairs, but Coq's kernel does not track which lemmas each tactic consults. The result: our extraction pipeline captures ~134,000 proof records containing ~105,000 unique goal states, but only ~3,500 produce non-empty premise lists usable as training pairs — a 97% attrition rate.

However, the extraction pipeline *does* capture the tactic text at each step (`ExtractionStep.tactic`). Every goal state has the tactic that was applied to it, regardless of whether that tactic's premises are known. This represents a 30× larger training signal that is currently discarded in the compact output format.

| Training signal | Available pairs | Source |
|----------------|----------------|--------|
| Premise retrieval (current) | ~3,500 | Steps with non-empty `premises` |
| Tactic prediction (proposed) | ~105,000 | All steps with `tactic` text |

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

### Phase 1: Emit tactic labels in extraction output

Extend `_write_result_compact` in `campaign.py` to emit a new record type `"s"` (step) containing the proof state and tactic text:

```json
{"t": "s", "f": "Arith/Plus.v", "s": "n : nat\nm : nat\nn + S m = S (n + m)", "c": "simpl"}
```

Fields: `t` = record type, `f` = source file, `s` = serialized proof state, `c` = tactic command text.

This requires no changes to the extraction backend — the data is already in `ExtractionStep.tactic`. Only the compact output writer needs updating.

### Phase 2: Tactic family classifier

Train a classifier on (proof_state → tactic_family) using the bi-encoder architecture:

1. Tokenize the proof state using the existing CodeBERT tokenizer
2. Encode via the bi-encoder's shared encoder (mean pooling → 768-dim)
3. Add a classification head mapping to the top-K tactic families
4. Train with cross-entropy loss on ~105K (state, tactic_family) pairs

The tactic family vocabulary can be derived from the extraction data. A reasonable starting set (~30 families covering >95% of steps):

`apply`, `rewrite`, `simpl`, `auto`, `induction`, `destruct`, `intros`, `exact`, `unfold`, `assert`, `exists`, `split`, `left`, `right`, `constructor`, `omega`/`lia`, `ring`, `reflexivity`, `symmetry`, `transitivity`, `case`, `elim`, `generalize`, `specialize`, `pose`, `set`, `change`, `pattern`, `ssreflect` (compound), `trivial`

### Phase 3: Tactic argument retrieval

For tactics that take lemma arguments (`apply`, `rewrite`, `exact`), combine the tactic family prediction with premise retrieval:

1. Predict tactic family from Phase 2
2. If the predicted tactic takes a lemma argument, run the existing premise retrieval pipeline to suggest candidates
3. Construct full tactic suggestions: `apply <candidate>`, `rewrite <candidate>`, etc.

This reuses the existing bi-encoder for premise retrieval but gates it behind tactic prediction, making the system more useful as a proof assistant.

### Phase 4: Integration as MCP tool

Expose tactic prediction as a new MCP tool `suggest_tactics` that takes a proof state and returns ranked tactic suggestions. This integrates directly into the existing proof session workflow.

## Advantages Over Current Approach

1. **30× more training data**: ~105K tactic-labeled states vs. ~3,500 premise pairs, from the same extraction output.
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

Some tactics (`auto`, `simpl`, `intros`) dominate the distribution. The classifier needs class weighting or focal loss to avoid degenerate predictions.

### SSReflect proofs

MathComp uses SSReflect's tactic language extensively. SSReflect compound tactics (e.g., `rewrite !addnA addnC`) pack multiple operations into a single step, making tactic family classification harder. These may need special handling or a separate SSReflect-aware head.

### Evaluation

Tactic prediction accuracy is not the same as proof completion rate. The model may predict the correct tactic family 80% of the time but still fail to produce a complete proof because the argument is wrong. Evaluation should track:
- Top-1 and top-5 tactic family accuracy
- Full tactic accuracy (exact match after normalization)
- Proof closure rate (can the predicted tactic close the current goal when executed?)

## Implementation Scope

| Phase | Effort | Dependencies |
|-------|--------|-------------|
| Phase 1: Emit tactic records | Small | None — data already available |
| Phase 2: Tactic classifier | Medium | Phase 1 + existing training infrastructure |
| Phase 3: Argument retrieval | Medium | Phase 2 + existing premise retrieval |
| Phase 4: MCP integration | Small | Phase 2 or 3 |

Phase 1 is nearly free — it's a ~10-line change to `_write_result_compact`. Phase 2 reuses the existing bi-encoder training infrastructure with a classification head instead of contrastive loss.

## Relationship to Other Work

- **Complements**: premise retrieval (tactic prediction selects the verb, retrieval selects the noun)
- **Supersedes**: cross-prover transfer training (uses existing Coq data instead of requiring Lean datasets)
- **Enables**: proof search / auto-completion in the MCP proof session tools
- **Blocked by**: nothing — the extraction data already exists
