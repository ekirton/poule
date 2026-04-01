# Proposal: Cross-Prover Transfer Training for Premise Selection

## Status

**Deprioritized.** With only ~3,500 Coq training pairs, the fine-tuning signal is too weak for any transfer strategy to be effective. The bottleneck is not the training algorithm — it is Coq's inability to report per-tactic premise usage. Until the Coq/Rocq kernel exposes premise tracking (similar to how Lean records lemma arguments in proof terms), no amount of transfer learning can compensate for the missing ground truth. The priority should be lobbying for LeanDojo-equivalent infrastructure in Rocq, or contributing premise-tracking instrumentation to the Rocq kernel.

## Problem

Neural premise selection for Coq suffers from a severe data scarcity bottleneck. The Coq ecosystem has no equivalent of LeanDojo's continuously-updated extraction infrastructure, which produces millions of (proof_state, premise) pairs from Lean's Mathlib. Our extraction pipeline processes ~134,000 proof records from stdlib + MathComp + stdpp + Flocq + Coquelicot + CoqInterval but yields only ~3,500 (proof_state, premises_used) training pairs — a 97% attrition rate caused by Coq's lack of per-tactic premise tracking (see §Problem below). By contrast:

| System | Pairs | Unique premises | Source |
|--------|-------|----------------|--------|
| LeanHammer (Lean) | 5,817,740 | 265,348 | Mathlib extraction |
| Magnushammer (Isabelle) | 4,400,000 | 433,000 | MAPL dataset |
| ReProver (Lean) | 129,243 tactics | 130,262 | LeanDojo/Mathlib |
| **Our pipeline (Coq)** | **~3,500** | **~22,000** | **stdlib + 5 libraries** |

Our training corpus is ~1,600× smaller than the Lean/Isabelle datasets that produced the best retrieval models. While training data quality matters more than quantity (LeanHammer's masked contrastive loss + rich extraction outperformed ReProver despite similar data scale), the Coq training set covers fewer mathematical domains and proof patterns.

**Why 134K proof records yield only 3,500 pairs.** Coq's kernel does not track which lemmas a tactic step actually uses. When a tactic like `auto`, `omega`, `lia`, or `ring` discharges a goal, it invokes internal decision procedures that do not report the premises they consulted. The extraction pipeline can only record premises when Coq's proof state explicitly references them (e.g., `apply`, `rewrite`, `exact`). Most proof steps — especially those using automation — produce empty premise lists and are discarded as training data. In Lean, `rw` and `simp` record their lemma arguments in the proof term, so LeanDojo extracts a premise annotation from nearly every tactic step. This structural difference in kernel-level premise tracking is the primary reason for the 40:1 extraction efficiency gap between Lean and Coq.

## Proposed Approach

### Strategy 1: Pre-train on Lean, fine-tune on Coq

Train the bi-encoder on LeanHammer's 5.8M (state, premise) pairs from Mathlib, then fine-tune on our Coq extraction data. The intuition: formal mathematics shares structural patterns across proof assistants — a rewrite with commutativity looks similar whether expressed in Lean or Coq.

**Evidence supporting this approach:**

- **PROOFWALA** (arXiv:2502.04671, 2025) demonstrated that models trained on both Lean 4 and Coq outperform monolingual models. Proof data synthesized across both systems improved performance on each system individually.
- **Cross-system steering vectors** work: PROOFWALA found that training data from one system provides useful inductive bias for the other.
- **Shared mathematical structure**: Both Lean and Coq formalize the same mathematics (natural number arithmetic, group theory, topology, analysis). The premise patterns overlap at the mathematical concept level even when the surface syntax differs.

**Training pipeline:**
1. Obtain LeanDojo's extracted dataset (publicly available via the LeanDojo Benchmark)
2. Serialize Lean proof states and premise statements using the same tokenizer (CodeBERT handles both)
3. Pre-train the bi-encoder with masked contrastive loss on the Lean data (~5.8M pairs)
4. Fine-tune on Coq extraction data with lower learning rate (5e-6) and fewer epochs (10)
5. Evaluate on Coq test split; compare against Coq-only baseline

**Estimated cost:** $200-400 for pre-training on Lean (1x A6000, ~6 days, matching LeanHammer's compute), plus our standard training cost for fine-tuning.

### Strategy 2: Joint training on Lean + Coq

Train on a mixed corpus of Lean and Coq data simultaneously, with a library-source indicator token prepended to each input. This avoids the catastrophic-forgetting risk of sequential pre-train/fine-tune and lets the model learn shared representations.

**Training pipeline:**
1. Combine Lean and Coq extraction data into a single JSONL stream
2. Prepend `[LEAN]` or `[COQ]` token to each proof state and premise statement
3. Train with standard masked contrastive loss on the combined corpus
4. At inference time, prepend `[COQ]` to queries and premises
5. Evaluate on Coq test split

### Strategy 3: Lean data as synthetic hard negatives

Use Lean premises as hard negatives when training on Coq data. The intuition: a Lean lemma about `Nat.add_comm` is semantically similar to Coq's `Nat.add_comm` but is not a valid retrieval target. This forces the model to learn Coq-specific representations while benefiting from Lean's broader coverage of mathematical concepts.

## Challenges

### Tokenization divergence

Lean 4 and Coq have different syntax, keywords, and naming conventions:
- Lean: `theorem add_comm : ∀ n m : Nat, n + m = m + n`
- Coq: `Lemma add_comm : forall n m : nat, n + m = m + n`

CodeBERT handles both as "code" but the token distributions differ. A domain-specific tokenizer (as CFR demonstrated for Lean alone, yielding +33% Recall@5) would need to cover both syntaxes.

### Semantic alignment

The same mathematical concept may have different names, different type signatures, and different proof structures across Lean and Coq. `Nat.add_comm` exists in both, but `List.map_comp` in Lean may correspond to `List.map_map` in Coq. The model must learn to align these despite surface differences.

### Evaluation fairness

Cross-system pre-training changes what the model has seen. Evaluation must ensure that the Coq test split contains no theorems whose Lean equivalents appeared in training. This requires a cross-library alignment dataset (which does not currently exist at scale).

### Data format harmonization

LeanDojo's extraction format differs from our JSONL format. A translation layer is needed:
- LeanDojo stores proof states as serialized Lean expressions; ours are pretty-printed Coq goals
- LeanDojo's premise annotations use Lean FQNs; ours use Coq FQNs
- The `TrainingDataLoader` would need to accept both formats or a unified intermediate format

## Why Deprioritized

1. **Insufficient fine-tuning data**: With ~3,500 Coq pairs, fine-tuning a model pre-trained on 5.8M Lean pairs would almost certainly overfit to the Coq data or catastrophically forget the Lean representations. The Coq fine-tuning set is too small to steer a pre-trained model toward Coq-specific retrieval patterns. This is not a hyperparameter tuning problem — it is a fundamental data scarcity problem.
2. **The real bottleneck is extraction, not training**: Coq's kernel does not track which lemmas each tactic consults. Until the Rocq kernel exposes per-tactic premise usage (as Lean does via proof term annotations), no training strategy can produce more than ~3,500 pairs from six libraries. The correct investment is kernel-level instrumentation, not training-time workarounds.
3. **Requires Lean infrastructure**: Obtaining and processing LeanDojo's dataset requires Lean 4 tooling that is outside our current dependency set.
4. **Uncertain magnitude**: While PROOFWALA shows cross-system benefits for proof generation, it has not been evaluated specifically for premise retrieval. The transfer benefit for retrieval may be smaller than for generation.
5. **Our model is small**: At 125M parameters (CodeBERT), the model may not have capacity to represent both Lean and Coq patterns effectively. Cross-prover transfer may benefit larger models (300M+) more.

## Prerequisites

- **Per-tactic premise tracking in Rocq**: Without this, the Coq fine-tuning set remains at ~3,500 pairs — too small for effective transfer. This is the blocking prerequisite.
- Solid Coq-only baseline: train and evaluate the model on Coq data alone first
- LeanDojo dataset access and format documentation
- Cross-library alignment data (even a small manually-curated set of Lean↔Coq theorem pairs for evaluation)
- GPU budget for the pre-training phase ($200-400)

## References

- PROOFWALA: arXiv:2502.04671, 2025. "Multilingual Proof Data Synthesis and Verification in Lean 4 and Coq."
- LeanDojo: Yang et al., NeurIPS 2023. "Theorem Proving with Retrieval-Augmented Language Models." Dataset publicly available.
- LeanHammer: Mikula et al., arXiv:2506.07477, June 2025. "Premise Selection for a Lean Hammer." 5.8M (state, premise) pairs from Mathlib.
- CFR: Zhu et al., arXiv:2501.13959, January 2025. Domain-specific tokenization yielded +33% Recall@5.
- RocqStar: arXiv:2505.22846, AAMAS 2026. Proof-similarity training on Coq with CodeBERT, 125M parameters.

## Relationship to Other Work

- **Blocked by**: per-tactic premise tracking in Rocq kernel (~3,500 pairs is insufficient for fine-tuning)
- Depends on: working Coq-only training pipeline (model, evaluation, quantization)
- Complements: extraction improvements (more Coq data reduces the relative importance of cross-prover transfer)
- Alternative to: proof-similarity training (RocqStar's approach bootstraps from Coq data only, without Lean)
