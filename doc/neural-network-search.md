# Neural Premise Selection for Coq/Rocq Libraries via Contrastive Bi-Encoder Retrieval

## Abstract

Premise selection — identifying which lemmas, definitions, and theorems from a formal library are relevant to a given proof goal — is a critical bottleneck in interactive theorem proving. While neural approaches to this problem have achieved strong results for Lean and Isabelle, the Coq/Rocq ecosystem lacks a neural retrieval system that integrates with practical tooling. We present a bi-encoder retrieval model for Coq premise selection, trained on proof traces extracted directly from compiled Coq libraries via a novel extraction pipeline. Our architecture employs a shared-weight CodeBERT encoder with a closed-vocabulary tokenizer built from the Coq declaration corpus, masked contrastive loss (InfoNCE), hard negatives sampled from the accessible premise set, and file-level data splitting to prevent leakage. The model produces 768-dimensional embeddings enabling sub-millisecond retrieval over corpora of 50K+ declarations. We describe the training data pipeline, which replays Coq proofs to recover per-step premise annotations — information not otherwise available in Coq's ecosystem — and the deployment path through INT8 quantization for CPU-only inference. The system is designed to complement existing symbolic retrieval channels (Weisfeiler-Lehman kernel hashing, Meng-Paulson symbol overlap, full-text search) via reciprocal rank fusion, following evidence that hybrid retrieval consistently outperforms any single signal.

## 1. Introduction

The Coq proof assistant and its successor Rocq implement the Calculus of Inductive Constructions (CIC), a dependently typed foundation used extensively in software verification (CompCert, Iris, VST), mathematics (the Four Color Theorem, Feit-Thompson), and programming language metatheory. Users of these systems routinely face a discovery problem: given a proof goal, which of the tens of thousands of available lemmas might help discharge it? Coq's built-in `Search` command provides syntactic pattern matching but no semantic understanding and no ranking. CoqHammer (Czajka and Kaliszyk, 2018) offers symbol-overlap-based premise selection but predates neural methods. The result is that Coq users rely heavily on manual memory and informal community knowledge to navigate libraries.

Meanwhile, neural premise selection has advanced rapidly in other proof assistants. ReProver (Yang et al., 2023) established the dense bi-encoder paradigm for Lean; LeanHammer (Mikula et al., 2025) demonstrated that an 82M-parameter encoder-only model with masked contrastive loss could outperform the 299M-parameter ReProver by 150% in end-to-end theorem proving; Magnushammer (Mikula et al., 2024) showed that a two-stage retrieve-then-rerank pipeline outperforms Sledgehammer's symbolic selection by 55% on Isabelle. These systems benefit from mature data extraction infrastructure — LeanDojo provides continuously updated proof traces for Lean's Mathlib — that does not exist for Coq.

The present work addresses this gap. We describe a neural premise selection system for Coq/Rocq that encompasses (1) a proof trace extraction pipeline producing per-step premise annotations from compiled Coq libraries, (2) a bi-encoder retrieval model trained with masked contrastive loss, (3) an evaluation framework comparing neural, symbolic, and hybrid retrieval, and (4) a deployment path through INT8 quantization enabling CPU-only inference at interactive latencies. The system is designed for integration into an MCP-based search server where an LLM acts as the downstream reasoning and reranking layer.

## 2. Background and Related Work

### 2.1 The Premise Selection Problem

Given a proof state (goal type and local hypotheses), premise selection ranks all available premises in a formal library by relevance, returning the top-*k* candidates. The problem is characterized by several challenges specific to formal mathematics:

**Scale.** Lean's Mathlib exceeds 210,000 theorems; Isabelle's Archive of Formal Proofs contains 433,000+ unique premises. Coq's combined libraries (Stdlib, MathComp, stdpp, Flocq, Coquelicot) contain tens of thousands of declarations. While smaller than Lean's corpus, the Coq library ecosystem spans diverse proof styles and notation conventions.

**Dependent type theory.** In CIC-based systems, definitional equality means that relevant premises may not appear syntactically in a proof. A tactic like `simpl` or `unfold` can invoke lemmas whose names never appear in the proof script, making ground truth extraction non-trivial.

**Distributional shift.** User-defined lemmas and newly added library content do not appear in training data, requiring generalization to unseen premises.

**Interactive latency.** Practical tools must return results within seconds to be useful during interactive proof development.

### 2.2 Symbolic and Classical Approaches

The earliest premise selection systems used hand-crafted features. **MePo** (Meng and Paulson, 2009) ranks premises by symbol overlap with the goal, iteratively expanding the symbol set through transitively related premises. Despite its simplicity, MePo achieves 42.1% Recall@32 on Lean's Mathlib — competitive with ReProver's 38.7% at the same cutoff. **SInE** (Hoder and Voronkov, 2011) uses trigger-based axiom selection via transitive symbol-overlap closure. **CoqHammer** (Czajka and Kaliszyk, 2018) combines symbol-overlap selection with translation to external ATPs and proof reconstruction; its premise selection uses term frequency and symbol overlap rather than learned representations.

These methods are fast and deterministic but cannot capture semantic relationships lacking surface-level syntactic overlap.

### 2.3 Neural Bi-Encoder Systems

The dominant paradigm for neural premise selection is the bi-encoder (dual-encoder): encode proof states and premise statements independently into a shared vector space, then retrieve by cosine similarity with precomputed premise embeddings. This architecture enables O(1) retrieval with approximate nearest-neighbor indices.

**ReProver** (Yang et al., 2023) established this paradigm for Lean using a ByT5-small (299M parameter) encoder with byte-level tokenization, mean-pooled contrastive embeddings, and in-file hard negative sampling. ReProver achieved 38.4% Recall@10 on Mathlib and 51.2% end-to-end theorem proving rate on the LeanDojo benchmark, trained on 129,243 tactic-premise pairs extracted via the LeanDojo infrastructure.

**LeanHammer** (Mikula et al., 2025) achieved the strongest reported retrieval metrics with a substantially smaller model. Using encoder-only transformers (23M–82M parameters) trained with masked contrastive loss (an InfoNCE variant that masks shared premises to prevent false negative signal), LeanHammer achieved 72.7% Recall@32 on Mathlib — nearly doubling ReProver's performance. Key to this result was richer ground truth extraction: LeanHammer captures implicit premises from `rw` and `simp` calls and term-style proofs that ReProver's extraction missed. The system uses accessible-set hard negatives (premises accessible via the dependency graph but unused in the proof) rather than random corpus negatives, and a low temperature (τ = 0.05) for sharp discrimination. The 82M-parameter model proves 150% more theorems than the 218M-parameter ReProver in the full pipeline evaluation.

**CFR** (Zhu et al., 2025) demonstrated the importance of domain-specific tokenization, training a custom WordPiece tokenizer on formal Lean corpora for a BERT-based retriever. This achieved 38.20% Recall@5 versus ReProver's 28.78% — a 33% relative improvement attributable primarily to the tokenizer, not model architecture or size. The companion CAR cross-encoder reranker further improved precision on top-ranked results.

**Lean Finder** (Lu et al., 2025) used a DeepSeek-Prover-V1.5-RL 7B decoder-as-encoder with two-stage training: contrastive learning across four query modalities (synthesized user queries, informalized statements, proof states, formal statements) followed by Direct Preference Optimization aligned with user search intent. Lean Finder achieved 64.2% Recall@1 on informalized statements and 81.6% preference rate in user studies, demonstrating the value of multi-modal query synthesis and user intent alignment. However, the 7B parameter count makes CPU deployment impractical.

### 2.4 Graph Neural Network Approaches

**Graph2Tac** (Blaauwbroek et al., 2024) is the most architecturally sophisticated system built specifically for Coq. It uses a GNN (implemented on TF-GNN) operating on Coq's term structure and dependency graph, with a novel online definition embedding task that computes representations for definitions unseen during training. Combined with a k-NN solver exploiting proof-level locality, Graph2Tac achieves 1.48× improvement over CoqHammer. Its key insight is that k-NN (locality) and GNN (structure) are highly complementary. However, Graph2Tac requires the Tactician platform infrastructure and has seen limited adoption.

An **RGCN-augmented** approach (Petrovcic et al., 2025) combined ReProver's text encoder with a Relational Graph Convolutional Network over a heterogeneous dependency graph, achieving +26% Recall@10 and +34% Recall@1 over the ReProver baseline. This provides the clearest evidence that dependency graph structure encodes signal that pure text-based embeddings miss.

### 2.5 Sparse and Hybrid Retrieval

**Rango** (Thompson et al., 2025; ICSE Distinguished Paper) produced a striking result for Coq: BM25 over proof states — treating formal identifiers as words — outperformed CodeBERT dense embeddings by 46% for in-project proof retrieval. Rango also demonstrated that per-step adaptive retrieval (re-retrieving at each proof step rather than once at the start) yields a 35% improvement over static retrieval. This finding suggests that lexical overlap of formal identifiers carries signal that dense embeddings can lose.

Hybrid dense-sparse retrieval has demonstrated strong results in general information retrieval — 66.3% NDCG@10 versus 55.4% for dense-only on MSMARCO — but has not been applied to formal mathematics. LeanHammer's best results come from the union of neural and MePo selections, achieving 21% improvement over neural-only, confirming that neural and symbolic selectors make complementary errors. LeanExplore (2025) demonstrated that an off-the-shelf 109M-parameter model (bge-base) with hybrid ranking (semantic embeddings + BM25 + PageRank) matched or exceeded a fine-tuned 7B model on many query types.

### 2.6 Proof-Similarity Training

**RocqStar** (JetBrains Research, 2025) introduced proof-similarity-driven embeddings for Coq/Rocq. Rather than training on statement similarity, RocqStar trains a CodeBERT encoder on proof similarity: two theorems with similar tactic sequences (measured by Levenshtein distance over tactic lists) are trained to be close in embedding space. Using the BigRocq dataset (76K statements from 4 Rocq projects), RocqStar achieved 28% relative improvement over Jaccard-based retrieval on a 300-theorem benchmark. The model (125M parameters) and training data are open-source.

### 2.7 Challenges in the Coq Ecosystem

Several challenges have impeded neural premise selection for Coq:

**Absence of extraction infrastructure.** Lean benefits from LeanDojo's continuously updated proof trace extraction, which produces millions of (state, premise) pairs from Mathlib. No equivalent exists for Coq. SerAPI (Gallego Arias, 2016) provides deep serialization but does not record per-step premise annotations. CoqGym (Yang and Deng, 2019) provides 71K proofs but is pinned to Coq 8.9 and has not been updated. BigRocq provides 76K statements but covers only 4 projects. The data bottleneck is the primary obstacle.

**Dependent type theory complications.** Coq's definitional equality, universe polymorphism, and canonical structures mean that the premises relevant to a tactic application may not be syntactically referenced. Extracting ground truth requires replaying proofs and inspecting the kernel's premise resolution, not merely parsing tactic names.

**Diverse notation and proof styles.** MathComp uses a distinctive proof style (ssreflect tactics, boolean reflection) that differs significantly from Stdlib's idioms. A model trained only on Stdlib may generalize poorly to MathComp and vice versa. Coq's extensible notation system means the same mathematical statement can have radically different surface syntax across libraries.

**Cold start.** With no large-scale Coq premise selection dataset, any new system must bootstrap from scratch. The strategies available are: (a) extract training data directly, (b) transfer from Lean (PROOFWALA, 2025, showed cross-system training benefits), or (c) use proof similarity as a proxy signal (RocqStar's approach).

### 2.8 Key Findings Informing Our Design

The literature reveals several consistent findings that have guided our architectural choices:

1. **Small models suffice.** LeanHammer (82M) outperforms ReProver (299M); LeanExplore (109M off-the-shelf) competes with fine-tuned 7B models; Magnushammer's 920K-parameter model outperforms Sledgehammer. For the 50K–200K declaration scale of Coq libraries, the embedding space does not require billions of parameters.

2. **Training data quality dominates model size.** LeanHammer's superior results come from better extraction (capturing implicit premises) and better training (masked contrastive loss), not more parameters. Magnushammer outperforms Sledgehammer with 0.1% of its training data when the data quality is high.

3. **Masked contrastive loss prevents false negatives.** Common premises (e.g., `Nat.add_comm`) appear as positives for many proof states. Standard in-batch contrastive loss treats these shared positives as negatives when they appear in other states' batches, degrading training. LeanHammer's masking eliminates this.

4. **Accessible-set hard negatives outperform random negatives.** Sampling negatives from premises that are accessible (respecting dependency ordering) but unused produces more informative training signal than random corpus sampling.

5. **Hybrid retrieval outperforms any single channel.** Rango's BM25 finding, LeanHammer's neural+MePo union, RGCN's text+graph fusion, and LeanExplore's semantic+lexical+PageRank combination all point to the same conclusion: no single retrieval signal dominates for formal mathematics.

6. **Domain-specific tokenization is critical.** CFR's custom tokenizer trained on formal Lean corpora produced +33% Recall@5 over a generic tokenizer — the single largest gain from any individual design decision. Rango's BM25 outperformance of CodeBERT embeddings (+46%) is partly a tokenization story: BM25 treats `Nat.add_comm` as a single lexical unit, while CodeBERT fragments it into five subword tokens. Coq's vocabulary is closed — every identifier in a proof state comes from the indexed declaration corpus, making subword tokenization unnecessary. Every identifier can be assigned its own token directly (~150K tokens across the six target libraries).

## 3. Methods

### 3.1 Training Data Extraction

Our training data is extracted from compiled Coq libraries by replaying each proof and recording per-step proof states and premise annotations. The extraction pipeline processes `.v` files from installed Coq library packages, producing JSON Lines output where each record represents one successfully extracted proof.

**Source libraries.** We extract from six Coq/Rocq libraries installed via opam:

| Library | Domain | Declarations |
|---------|--------|-------------|
| Stdlib | Standard library (arithmetic, logic, data structures) | ~31,000 |
| MathComp | Formalized mathematics (algebra, finite groups, field theory) | ~58,000 |
| stdpp | Iris-style proof patterns, general-purpose extensions | ~5,000 |
| Flocq | Floating-point arithmetic formalization | ~2,600 |
| Coquelicot | Real analysis | ~2,400 |
| Interval | Interval arithmetic | ~20,000 |

Of the declarations with proof bodies in each library, extraction success rates vary: Stdlib yields ~3,000 proof traces (~20% of declarations with proof bodies), while MathComp yields ~300 (~2%). The low rates reflect the prevalence of auto-generated and Include'd declarations that have opaque proof terms but no extractable tactic scripts — a structural limitation of the Coq ecosystem discussed in detail below.

**Extraction backend: coq-lsp.** The extraction pipeline uses coq-lsp (Gallego Arias et al.) as the backend for proof replay. coq-lsp implements the Language Server Protocol over Coq's document model, providing two capabilities critical for training data extraction: (1) *document-level proof navigation* — the ability to jump to any proof in a loaded `.v` file by position, preserving the full context of Section variables, local notations, and imported modules; and (2) *proof state introspection* — access to the structured proof state (goals, hypotheses, focused goal index) at each tactic step via the `proof/goals` protocol.

We evaluated coqtop (Coq's command-line REPL) as an alternative backend. coqtop processes Vernacular commands sequentially over stdin/stdout, which is simpler to implement. However, coqtop cannot navigate to an arbitrary proof within an already-loaded file. The workaround — loading the entire file (which type-checks all proofs through `Qed`), then re-entering each proof via `Goal <type>.` followed by tactic replay — fails in three common situations:

1. **Section variables.** Proofs inside `Section` blocks reference variables declared with `Variable` or `Hypothesis`. These variables are in scope during the original proof but not available in a standalone `Goal` context. In Stdlib's `Between.v`, all proofs reference section variables `P` and `Q`; the `Goal` command fails because these names are unbound.

2. **Scoped notations.** Coq's `Local Open Scope` and library-specific notations (e.g., MathComp's `%:R`, `\is`, ssreflect's `//=`) are available during proof development but not in a bare `Goal` context after the file is loaded. The `Goal` parser rejects theorem types containing these notations.

3. **Include'd and functor-generated proofs.** Declarations introduced via `Include M` or functor application (`Module N := F A`) exist in the loaded environment but have no proof script in the host `.v` file. coqtop cannot replay what does not exist in the source.

In empirical testing across six libraries, coqtop extracted 4,275 proof traces (plus 196 partial):

| Library | Theorems | coqtop extracted | coqtop failed | coqtop no proof body |
|---------|----------|-----------------|---------------|---------------------|
| Stdlib | 14,721 | 3,015 | 47 | 11,531 |
| MathComp | 15,711 | 308 | 19 | 15,375 |
| Flocq | 2,081 | 415 | 1 | 1,652 |
| Coquelicot | 1,809 | 286 | 13 | 1,487 |
| Coq-Interval | 811 | 243 | 2 | 543 |
| stdpp | 3,460 | 8 | 5 | 3,447 |
| **Total** | **38,593** | **4,275** | **87** | **34,035** |

The "no proof body" column — 88% of all declarations — represents the combined effect of all three failure categories. coq-lsp recovers a significant fraction of the category 1 and 2 failures (section variables and scoped notations), yielding approximately twice the training data from the same libraries. Category 3 failures (Include'd and functor-generated proofs) affect both backends equally. coq-lsp's document model avoids these issues entirely because it navigates within the document's existing proof context rather than reconstructing it from scratch.

**Proof trace structure.** For each successfully extracted proof, the pipeline records a sequence of steps. Each step contains: (a) the proof state after the tactic application (goal types and hypotheses), and (b) the premises used by that tactic (with kind annotations distinguishing global declarations from local hypotheses). Step 0 is the initial state with no tactic.

**Proof state, tactics, goals, and hypotheses.** A *proof state* is a snapshot of the Coq proof environment at a single point in time. It contains a list of *goals* — the propositions that remain to be proved — and a *focused goal index* indicating which goal the next tactic will act on. Each goal carries its own list of *hypotheses*: the named assumptions in scope above the turnstile (⊢). For example, in the context `n : nat, IHn : P n ⊢ P (S n)`, `n` and `IHn` are hypotheses and `P (S n)` is the goal type.

A *tactic* is a proof command that transforms one proof state into the next. Different tactics affect the goal list in different ways: `induction n` replaces one goal with a base case and inductive step (increasing the goal count); `split` decomposes a conjunction into two subgoals; `exact` or `reflexivity` discharges the focused goal entirely (decreasing the count); `rewrite` modifies the focused goal's type while preserving the hypothesis context. When the goal list is empty, the proof is complete.

The extraction pipeline records a `TraceStep` for each tactic application. Each `TraceStep` pairs a tactic string with the `ProofState` that results *after* executing that tactic. Step 0 is the initial state (no tactic); steps 1 through *N* each record both the tactic and its resulting state. The full proof trace is the sequence `[step_0, step_1, …, step_N]`, where `step_N.state.goals` is empty for a complete proof.

Concretely, a proof of `forall n, n + 0 = n` produces a trace like:

| Step | Tactic | Goals after | Hypotheses (focused goal) | Premises used |
|------|--------|-------------|---------------------------|---------------|
| 0 | *(none)* | `n + 0 = n` | `n : nat` | — |
| 1 | `induction n` | `0 + 0 = 0`; `S n + 0 = S n` | goal 0: *(none)*; goal 1: `n : nat`, `IHn : n + 0 = n` | `nat_ind` |
| 2 | `reflexivity` | `S n + 0 = S n` | `n : nat`, `IHn : n + 0 = n` | `eq_refl` |
| 3 | `simpl; rewrite IHn; reflexivity` | *(empty — proof complete)* | — | `IHn` |

This structure means each training example has access to the full proof context — not just the tactic text, but the precise set of goals and hypotheses that motivated the tactic choice and determined which premises were relevant.

**Training pair construction.** From the step sequence, we construct (proof_state, premises_used) pairs by pairing the goals from step *k*−1 (the state *before* the tactic) with the global premises from step *k* (the premises the tactic consumed):

```
For each proof trace:
  For step k = 1 to len(steps) - 1:
    state_text = serialize_goals(steps[k-1].goals)
    premises   = [p.name for p in steps[k].premises if p.kind ≠ "hypothesis"]
    If premises is non-empty:
      Emit (state_text, premises)
```

Local hypotheses (`kind: "hypothesis"`) are excluded because they are proof-internal bindings that do not correspond to entries in the declaration corpus; including them would produce positive labels for items that can never be retrieved, degrading training quality. Steps with no premises (e.g., `reflexivity`, `assumption`) are skipped as they provide no retrieval training signal.

**Proof state serialization.** The structured goal list is serialized to a deterministic text string. For each goal, hypotheses are listed as `name : type` on separate lines, followed by the goal type. Multiple goals are separated by a blank line. For example:

```
n : nat
m : nat
H : n <= m
────────────────────────────────────────
m - n + n = m
```

**Example training pair.** Consider a proof of `Nat.sub_add` containing a step that applies `rewrite Nat.add_comm`. The training pair would be:

- **Proof state** (before the tactic): the goal `n + (m - n) = m` with hypotheses `n m : nat`, `H : n <= m`
- **Premises used** (by the tactic): `["Nat.add_comm"]`

**Compact training data format.** The extraction pipeline writes training data in a compact JSONL format: `"p"` records store `(source_file, state_text, used_premises)` training pairs, and `"g"` records store supplementary goal states for vocabulary construction. Non-proof records (campaign metadata, extraction errors, summaries) are included unchanged. This avoids the 180 GB full proof-trace JSONL that earlier versions produced (each step recorded up to 16K accessible premises).

**Memory-efficient loading.** The data loader interns all premise name strings (`sys.intern()`) to avoid duplicating the ~22K unique names across ~27M references, reducing memory from ~2.7 GB to <1 MB. A `SQLitePremiseCorpus` replaces the in-memory premise corpus dict, keeping only names in RAM and fetching statement text from the database on demand (saving ~500 MB+ of UCS-2 strings). After JSONL parsing, `malloc_trim` returns freed memory to the OS.

**Data quality.** The extraction pipeline produces a campaign metadata record (Coq version, project commits, tool version) and an extraction summary with counts. The `validate-training-data` command checks for: >10% empty-premise steps, malformed fields, fewer than 5,000 pairs, fewer than 1,000 unique premises, and any single premise exceeding 5% of all occurrences. The six target libraries yield approximately 134,000 extracted proof records but only ~3,500 (proof_state, premises_used) training pairs (stdlib 2,071, mathcomp 546, flocq 504, coqinterval 268, coquelicot 140, stdpp 0) — the gap reflects the high proportion of proof steps with empty premise lists.

**The Coq training data gap.** The ~3,500 training pairs extractable from six Coq libraries represent a fundamental limitation compared to the Lean ecosystem. LeanDojo extracts 129,243 tactic-premise pairs from Lean's Mathlib alone — over 35× more training data from a single library. LeanHammer further improves on this by capturing implicit premises from `rw` and `simp` calls. This gap has four structural causes:

1. **Opaque proof terms.** When a Coq proof is closed with `Qed`, the proof term becomes opaque — the kernel retains it for type-checking but does not expose it for inspection. Extracting per-step premises requires replaying the proof interactively, which succeeds only when the `.v` source file contains an explicit tactic script. Declarations introduced via `Include`, functor application, or automation (HB.instance, Canonical Structure) have proof terms but no tactic script, making them invisible to the extraction pipeline. In our six target libraries, only 4,275 of 38,593 declarations with proof bodies (11%) yield extractable tactic proofs. The remaining 89% are opaque with no accessible script.

2. **No per-tactic premise tracking.** Even when a proof is successfully extracted, Coq's kernel does not track which lemmas each tactic step actually uses. Tactics like `auto`, `omega`, `lia`, and `ring` invoke internal decision procedures that do not report the premises they consult. The extraction pipeline can only record premises when Coq's proof state explicitly references them (e.g., `apply`, `rewrite`, `exact`). The result is a 97% attrition rate: of ~134,000 extracted proof records, only ~3,500 produce non-empty premise lists usable as training pairs. By contrast, Lean's `rw` and `simp` record their lemma arguments in the proof term, so LeanDojo extracts a premise annotation from nearly every tactic step.

3. **Multi-step proofs are short.** Coq proofs that do yield training pairs tend to be shorter than Lean proofs. SSReflect-style proofs (dominant in MathComp) use tactic combinators that compress multi-step reasoning into single compound tactics, further reducing the number of training pairs per proof.

4. **Library scale.** Lean's Mathlib contains 210,000+ theorems in a single unified library with consistent tooling. Coq's ecosystem is fragmented across independently maintained libraries (Stdlib, MathComp, stdpp, Flocq, Coquelicot, Interval) totaling ~120K declarations, each with different proof styles, notation conventions, and build systems.

The net effect is that training a competitive neural premise selector for Coq requires either (a) significantly more extractable training data from the Coq ecosystem, (b) cross-system transfer learning from Lean (as demonstrated by PROOFWALA), or (c) alternative training signals such as proof similarity (RocqStar's approach). See §5 for a discussion of what changes to the Coq/Rocq framework would enable Lean-comparable extraction.

**Implications for model training.** With ~3,500 pairs, the training set is roughly 1,600× smaller than LeanHammer's 5.8M. This severely limits the effective batch size for contrastive learning (fewer in-batch negatives), reduces premise coverage (most library premises never appear as positives), and increases the risk of overfitting. The masked contrastive loss and accessible-set hard negatives partially mitigate these issues by maximizing the information content of each training example, but the data bottleneck remains the primary obstacle to achieving Lean-competitive retrieval quality.

### 3.2 Data Splitting

The dataset is split at the file level, not the pair level, to prevent data leakage from related proofs in the same file. Source files are sorted lexicographically by fully qualified path, then assigned deterministically by position modulo 10:

| Position mod 10 | Split |
|-----------------|-------|
| 0–7 | Training (80%) |
| 8 | Validation (10%) |
| 9 | Test (10%) |

All pairs from the same `.v` file reside in exactly one split.

### 3.3 Hard Negative Sampling

Effective contrastive learning requires informative negative examples. Following LeanHammer's accessible-set strategy, we sample hard negatives from premises that are *accessible* to the theorem (their source file appears in the transitive file-dependency closure of the theorem's file) but were *not used* in the proof step:

```
accessible_files(theorem) = transitive closure of file-level imports from theorem's source file
accessible_premises(theorem) = all premises defined in accessible_files(theorem)
hard_negatives = sample(accessible_premises \ positive_premises, k=3)
```

This produces negatives that are semantically proximate (they concern related mathematical topics, since they are in dependency-related files) but incorrect for the specific goal. When the dependency graph is unavailable, the system falls back to random corpus sampling.

### 3.4 Model Architecture

We employ a bi-encoder with shared weights: a single encoder processes both proof states and premise statements, mapping them into a shared 768-dimensional embedding space.

**Tokenization.** We replace CodeBERT's default RoBERTa BPE tokenizer (50,265-token vocabulary trained on English text and general-purpose code) with a **closed-vocabulary tokenizer** that assigns every library identifier, syntax token, and Unicode symbol its own token ID. This follows CFR's finding that domain-specific tokenization produced a +33% Recall@5 improvement on formal Lean corpora — the single largest gain from any individual design decision.

CodeBERT's generic tokenizer over-segments Coq syntax: `Nat.add_comm` becomes 5 tokens (`Nat`, `.`, `add`, `_`, `comm`), `mathcomp.algebra.ssralg` becomes 9 tokens, and Unicode symbols (`∀`, `→`, `⊢`) may map to unknown tokens or multi-byte fallback sequences. This over-segmentation wastes the 512-token context window and fragments semantically meaningful identifiers.

Unlike natural language, Coq's vocabulary is closed: every identifier in a proof state comes from the indexed declaration corpus (~118K declarations across 6 libraries), plus ~33K variable names and syntax fragments from training data, ~110 fixed syntax/punctuation tokens, and 64 Unicode symbols — approximately 150K tokens total. This makes subword tokenization (WordPiece, BPE) unnecessary. The closed-vocabulary tokenizer performs a simple whitespace split followed by O(1) dictionary lookup per token, achieving perfect fertility (1 token per identifier, always) with no regex pre-tokenizer complexity. NFC Unicode normalization is applied before tokenization. Unknown tokens map to `[UNK]`.

The full tokenizer design — including the closed-vocabulary rationale, subword alternatives considered, vocabulary construction, and evaluation methodology — is described in `coq-vocabulary.md`.

**Base encoder.** The encoder is initialized from CodeBERT (microsoft/codebert-base), a 125M-parameter transformer pretrained on six programming languages via masked language modeling and replaced token detection. We chose CodeBERT over alternatives for several reasons: (a) it handles formal syntax better than general NLP models while remaining smaller than 7B decoder-based alternatives; (b) RocqStar demonstrated its suitability for Coq embeddings; (c) at 125M parameters, it permits full fine-tuning on a single consumer GPU and INT8 quantization for CPU deployment at <10ms per encoding.

**Embedding layer initialization.** The closed vocabulary (~150K tokens) differs from CodeBERT's pretrained embedding layer (50,265 tokens). We create a new `nn.Embedding(vocab_size, 768)`: tokens that overlap with CodeBERT's original vocabulary (digits, punctuation, common English words like `nat`, `list`, `bool`) retain their pretrained embeddings; Coq-specific tokens (`Nat.add_comm`, `ssreflect`, `∀`) are initialized randomly (normal distribution, σ = 0.02). CodeBERT's 12 transformer layers retain their full pretrained weights. Contrastive fine-tuning provides sufficient signal for the new embeddings to converge.

**Pooling.** Token-level outputs are combined via mean pooling over non-padding positions, followed by L2 normalization. This produces unit-length embeddings where cosine similarity reduces to dot product.

**Architecture summary:**

```
Input text (proof state or premise statement)
  → NFC Unicode normalization
  → Whitespace tokenization
  → Closed-vocabulary lookup (~150K tokens)
  → token_ids, attention_mask (max length 512)
  → CodeBERT encoder (125M params, 12 layers, 768 hidden)
  → Mean pooling over non-padding tokens
  → L2 normalization
Output: embedding ∈ ℝ^768, ||embedding|| = 1
```

The shared-weight design means proof states and premise statements share the same encoder and embedding space. During training, both are encoded by the same network. At inference time, premise embeddings are precomputed once and stored; only the query proof state requires online encoding.

### 3.5 Training Objective

We use masked contrastive loss, an InfoNCE variant introduced by LeanHammer that addresses the shared-premise problem in formal mathematics.

**The shared-premise problem.** Standard in-batch contrastive loss treats all non-positive premises in a batch as negatives. In formal mathematics, common lemmas (e.g., `Nat.add_comm`, `eq_refl`) are positive for many proof states. When two states in the same batch share a positive premise, the standard loss penalizes the model for assigning high similarity to the shared premise — a false negative signal that degrades embedding quality.

**Masked contrastive loss.** For a batch of *B* proof states {*s*₁, …, *s*_*B*}, each with positive premises *P*_*i* and hard negatives *N*_*i*:

For each positive pair (*s*_*i*, *p*_*ij*):

$$\mathcal{L}_{ij} = -\log \frac{\exp(\text{sim}(s_i, p_{ij}) / \tau)}{\sum_{c \in \mathcal{C}_{ij}} \exp(\text{sim}(s_i, c) / \tau)}$$

where the candidate set *C*_*ij* = {*p*_*ij*} ∪ *N*_*i* ∪ {*p*_*kl* : *k* ≠ *i*, *p*_*kl* ∉ *P*_*i*}, sim(·,·) is cosine similarity, and τ = 0.05 is the temperature. The masking condition *p*_*kl* ∉ *P*_*i* ensures that premises which are positive for *s*_*i* are excluded from the negative set, even when they appear as positives for other states in the batch.

**Hyperparameters:**

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Batch size | 128 | Effective batch via gradient accumulation (micro-batch 32) |
| Learning rate | 5 × 10⁻⁵ | Standard for CodeBERT fine-tuning |
| Weight decay | 10⁻² | AdamW regularization |
| Temperature τ | 0.05 | Sharp discrimination; matches LeanHammer |
| Hard negatives per state | 3 | Matches LeanHammer's *B*⁻ = 3 |
| Max positives per pair | 16 | Caps premise count to bound activation memory |
| Max sequence length | 256 tokens | Sufficient for Coq proof states and premises |
| Max epochs | 20 | With early stopping |
| Early stopping patience | 3 | Halt when validation Recall@32 plateaus |

Training uses mixed-precision (FP16) on CUDA GPUs with gradient accumulation (micro-batch size 32). Premise encoding is performed without gradient tracking — the shared-weight encoder learns from state-side gradients — and chunked into batches of 64 to bound peak activation memory.

### 3.6 Evaluation

**Retrieval metrics.** We evaluate on the held-out test split using Recall@*k* for *k* ∈ {1, 10, 32} and Mean Reciprocal Rank (MRR). Recall@32 is the primary metric, following LeanHammer's convention: it measures whether the correct premise appears within the top 32 retrieved candidates — sufficient for downstream consumption by a tactic generator or LLM reasoning layer.

**Comparison protocol.** We evaluate three retrieval configurations: (a) neural-only (bi-encoder cosine similarity), (b) symbolic-only (Weisfeiler-Lehman kernel hashing + Meng-Paulson symbol overlap + FTS5 full-text search), and (c) union (neural + symbolic, fused via reciprocal rank fusion). The key metric is relative improvement: (union Recall@32 − symbolic Recall@32) / symbolic Recall@32.

**Deployment gates** (advisory thresholds):
- Neural Recall@32 ≥ 50%
- Union relative improvement ≥ 15% over symbolic-only

### 3.7 Quantization and Deployment

The trained PyTorch checkpoint is converted to INT8 ONNX for CPU inference via a three-step quantization pipeline:

1. **Export** the model to ONNX format (opset 17+)
2. **Quantize** via ONNX Runtime dynamic INT8 quantization, reducing model size from ~400MB to ~100MB
3. **Validate** by encoding 100 random inputs through both models, failing if max cosine distance ≥ 0.02

The quantized model runs at <10ms per encoding on CPU, enabling sub-second retrieval for interactive use. At startup, premise embeddings are loaded into a FAISS `IndexFlatIP` index from a `.faiss` sidecar file for exact inner product search. A dual storage model separates the write path (SQLite `embeddings` table stores raw vectors during indexing) from the read path (`.faiss` sidecar generated at finalization). The sidecar can be regenerated from SQLite without re-encoding, supporting migration from pre-FAISS databases. Retrieval is then a FAISS inner product search followed by top-*k* selection.

### 3.8 Integration with Hybrid Retrieval

The neural retrieval channel is one of several in the search pipeline. At query time, a proof state is encoded and compared against precomputed premise embeddings via cosine similarity. The neural rankings are fused with symbolic channel rankings (WL kernel, MePo symbol overlap, FTS5) using weighted reciprocal rank fusion (WRRF):

$$\text{WRRF}(d) = \sum_{c \in \text{channels}} \frac{w_c}{k + \text{rank}_c(d)}$$

The smoothing constant *k* and per-channel weights *w_c* are optimized via Optuna in a three-phase pipeline: (1) optimize *k* and weights for the three symbolic channels alone, (2) train the neural model with HPO, (3) optimize *k* and weights for all four channels jointly. Phases 1 and 2 are independent; phase 3 requires the trained model from phase 2. The optimization uses the validation split and pre-computes all channel ranked lists once — each Optuna trial only re-fuses, making it sub-second. See `doc/reciprocal-rank-fusion.md` §5 for the full protocol.

The fused ranking is returned to an LLM reasoning layer via MCP, which serves as an implicit reranking and reasoning stage — performing a function analogous to the cross-encoder reranking stage in systems like Magnushammer, but with the additional capability of incorporating contextual reasoning about the proof state.

## 4. Evaluation

The central claim of this work is that adding a neural retrieval channel to the existing symbolic pipeline improves premise selection quality. This section describes the experimental protocol for testing that claim.

### 4.1 Experimental Setup

**Test corpus.** Evaluation uses the held-out test split (10% of source files, selected by position mod 10 = 9 as described in §3.2). All (proof_state, premises_used) pairs from test-split files are evaluation queries. The premise corpus is the full set of declarations from the six target libraries (~34,000 declarations across Stdlib, MathComp, stdpp, Flocq, Coquelicot, and Interval).

**Hardware.** All retrieval latency measurements use CPU-only inference with the INT8 quantized model (§3.7). No GPU is used at evaluation time, matching the deployment target.

### 4.2 Baseline: Symbolic Pipeline

The baseline is the existing symbolic retrieval pipeline operating without the neural channel. It comprises four channels fused via weighted RRF with empirically optimized *k* and per-channel weights (see §3.8):

| Channel | Algorithm | Signal |
|---------|-----------|--------|
| Structural | Weisfeiler-Lehman kernel hashing | Term structure similarity |
| Fine Structural | Tree Edit Distance | Fine-grained structural comparison |
| Symbol Overlap | Meng-Paulson (MePo) | Iterative breadth-first symbol overlap |
| Lexical | FTS5 with BM25 | Full-text lexical matching |

This symbolic pipeline, with optimized fusion parameters, is the base model against which the neural channel must demonstrate improvement. It represents the strongest retrieval configuration achievable without learned embeddings or training data.

### 4.3 Retrieval Configurations

We evaluate three retrieval configurations to isolate the neural channel's contribution, corresponding to the three-phase optimization pipeline described in `doc/reciprocal-rank-fusion.md` §5.3:

1. **Symbolic-only.** The four symbolic channels (§4.2) fused via weighted RRF with optimized *k* and weights from phase 1. This is the baseline.
2. **Neural-only.** Bi-encoder cosine similarity retrieval using the trained model (§3.4). No symbolic channels. Evaluated after phase 2 (neural training with HPO).
3. **Hybrid.** All five channels (four symbolic + neural) fused via weighted RRF with separately optimized *k* and weights from phase 3. This is the target deployment configuration.

The *k* values for symbolic-only and hybrid configurations may differ, since the neural channel's rank distribution changes the fusion dynamics.

### 4.4 Metrics

**Primary metric.** Recall@32 — the fraction of evaluation queries for which the correct premise appears within the top 32 retrieved candidates. This cutoff follows LeanHammer's convention and represents a practical budget for downstream consumption by a tactic generator or LLM reasoning layer.

**Secondary metrics.** Recall@1, Recall@10, and Mean Reciprocal Rank (MRR) provide additional resolution across the ranking.

**Relative improvement.** The key measure of the neural channel's value is:

$$\Delta = \frac{\text{Recall@32}_{\text{hybrid}} - \text{Recall@32}_{\text{symbolic}}}{\text{Recall@32}_{\text{symbolic}}}$$

### 4.5 Complementarity Analysis

Following LeanHammer's union analysis methodology, we partition the set of correctly retrieved premises into three categories:

- **Symbolic-only hits:** premises retrieved by the symbolic pipeline but missed by the neural channel
- **Neural-only hits:** premises retrieved by the neural channel but missed by the symbolic pipeline
- **Shared hits:** premises retrieved by both

The neural channel justifies its inclusion if the neural-only hit fraction is substantial — indicating that it captures premises invisible to symbolic matching. A channel that only duplicates symbolic hits adds fusion overhead without retrieval benefit.

### 4.6 Latency Evaluation

| Measurement | Target | Method |
|-------------|--------|--------|
| Neural encoding latency | < 100ms per query | Median over all test queries on CPU with INT8 model |
| End-to-end hybrid retrieval | < 1 second | Wall-clock time from query input to ranked result list, including all channels and fusion |
| Index rebuild | < 10 minutes for 50K declarations | Wall-clock time to encode all premises and build the retrieval index |

### 4.7 Success Criteria

The neural channel is considered successful if both conditions are met on the held-out test set:

1. **Neural retrieval quality.** Neural-only Recall@32 ≥ 50%.
2. **Hybrid improvement.** Hybrid Recall@32 achieves ≥ 15% relative improvement over symbolic-only Recall@32.

These thresholds are advisory deployment gates, not hard constraints. A model that narrowly misses one threshold but demonstrates strong complementarity (§4.5) may still warrant deployment. Conversely, a model meeting both thresholds but showing negligible neural-only hits would suggest the improvement comes from fusion noise rather than genuine complementary signal.

### 4.8 RRF Tuning Results

RRF fusion parameters were optimized in two phases using Optuna on the validation split (292 queries).

**Phase 1: Symbol-only** (3 channels, 30 trials)

| Parameter | Value |
|-----------|-------|
| *k* | 38 |
| *w*_structural | 1.901 |
| *w*_mepo | 1.464 |
| *w*_fts | 1.197 |
| Recall@32 (val) | 0.68% |

**Phase 2: Combined** (4 channels including neural, 50 trials)

| Parameter | Value |
|-----------|-------|
| *k* | 16 |
| *w*_structural | 0.116 |
| *w*_mepo | 1.732 |
| *w*_fts | 1.202 |
| *w*_neural | 1.416 |
| Recall@32 (val) | 8.9% |

**Observations.** Adding the neural channel increased validation Recall@32 from 0.68% to 8.9% — a 13× absolute improvement, with the neural channel receiving the second-highest weight (1.416) behind MePo (1.732). The structural channel weight dropped from 1.901 (symbolic-only) to 0.116 (combined), indicating that the neural channel subsumes most of the signal previously provided by WL kernel hashing. The lower *k* value (16 vs. 38) reflects the neural channel's sharper rank distribution compared to the symbolic channels.

The low absolute Recall@32 values reflect the difficulty of the task: the premise corpus contains ~118,000 declarations, and only ~3,500 training pairs were available. With Lean-scale training data (100K+ pairs), these numbers would be expected to improve substantially.

## 5. Toward Lean-Comparable Training Data Extraction for Coq

The ~15× training data gap between Coq and Lean is not inherent to the mathematics formalized in these systems — it reflects differences in proof assistant architecture and tooling. This section identifies the specific capabilities that would enable Lean-comparable extraction from Coq/Rocq.

### 5.1 The Core Problem: Proof Term Opacity

Lean's kernel stores proof terms in a structured format (`.olean` files) that LeanDojo can traverse programmatically to extract premise dependencies at every tactic step. When a Lean user writes `simp [Nat.add_comm, Nat.mul_assoc]`, LeanDojo can inspect the resulting proof term to identify exactly which lemmas the simplifier invoked — including internal lemmas the user did not name explicitly.

Coq's `Qed` command deliberately makes proof terms opaque: the kernel verifies the proof but discards the term's internal structure from the `.vo` file's public interface. This design choice (motivated by compilation performance and proof irrelevance) means that external tools cannot inspect which lemmas a completed proof used without replaying it from source. The consequence is that only proofs with explicit tactic scripts in `.v` files are extractable, excluding the large class of proofs generated by Include, functor instantiation, and proof automation.

### 5.2 Required Framework Capabilities

The following capabilities, if added to Coq/Rocq, would close the extraction gap:

**1. Proof term introspection API.** A kernel-level API that, given a fully qualified name, returns the proof term in a structured traversable format (analogous to Lean's `Environment.find?`). This would enable extracting premise dependencies from any declaration — including opaque proofs, functor-generated proofs, and automation-generated proofs — without requiring `.v` source access or interactive replay. The API would need to expose the term's constants, inductive types, and constructor references at each sub-term level.

**2. Per-tactic premise recording during proof checking.** During interactive proof development or batch compilation, the kernel could record which constants each tactic invocation resolved to. This metadata — a list of `(tactic_text, [premise_names])` pairs — could be serialized alongside the `.vo` file (e.g., in a `.vo.trace` sidecar). This is precisely what LeanDojo captures from Lean's elaboration trace. Coq's tactic engine already has this information internally during proof construction; it is simply not persisted.

**3. Elaboration trace export.** A more general version of capability 2: export the full elaboration trace (the sequence of kernel-level operations performed during tactic evaluation) in a machine-readable format. This would capture not only direct premise usage but also the intermediate goals, unification steps, and automation decisions that led to each proof step. This is the richest possible training signal, enabling extraction of implicit premises from tactics like `auto`, `omega`, and `ring` that currently produce no training data.

### 5.3 Interim Mitigations

Until framework-level changes are available, several strategies can partially close the gap:

- **Cross-system transfer.** PROOFWALA (2025) demonstrated that models trained on Lean proof data can transfer to Coq, suggesting that the mathematical reasoning patterns are partially shared across proof assistants.
- **Proof similarity training.** RocqStar's approach — training on tactic sequence similarity rather than explicit premise annotations — does not require per-step premise extraction and can leverage all proofs with tactic scripts, including those where premise resolution fails.
- **Synthetic data augmentation.** Proof states can be augmented by applying type-preserving transformations (variable renaming, hypothesis reordering, goal specialization) to expand the effective training set from existing extractions.
- **coq-dpdgraph dependency extraction.** The coq-dpdgraph tool extracts theorem-to-theorem dependencies from compiled `.vo` files via the kernel's internal dependency tracking. While it provides only proof-level (not step-level) premise annotations, it covers all opaque proofs and could supplement the per-step data with weaker but broader training signal.

## References

Blaauwbroek, L., Olšák, M., Rute, J., Massolo, F.N., and Piepenbrock, J. "Graph2Tac: Online Representation Learning of Formal Math Concepts." *Proceedings of the 41st International Conference on Machine Learning (ICML)*, 2024.

Cao, H., et al. "Library Learning Doesn't: The Curious Case of the Single-Use Library." *Advances in Neural Information Processing Systems (NeurIPS)*, 2024.

Czajka, Ł. and Kaliszyk, C. "Hammer for Coq: Automation for Dependent Type Theory." *Journal of Automated Reasoning*, 61(1-4):423–453, 2018.

Gallego Arias, E.J. "SerAPI: Machine-Friendly, Data-Centric Serialization for Coq." Technical report, 2016.

Han, J., Rens, A., Wu, Y., Szegedy, C., and Stich, S.U. "Proof Artifact Co-Training for Theorem Proving with Language Models." *International Conference on Learning Representations (ICLR)*, 2022.

Hoder, K. and Voronkov, A. "Sine Qua Non for Large Theory Reasoning." *International Conference on Automated Deduction (CADE)*, 2011.

Lu, Y., et al. "Lean Finder: Semantic Search for Mathlib That Understands User Intents." *AI4Math Workshop at ICML*, 2025.

Meng, J. and Paulson, L.C. "Lightweight Relevance Filtering for Machine-Generated Resolution Problems." *Journal of Applied Logic*, 7(1):41–70, 2009.

Mikula, M., et al. "Magnushammer: A Transformer-Based Approach to Premise Selection." *International Conference on Learning Representations (ICLR)*, 2024.

Mikula, M., et al. "Premise Selection for a Lean Hammer." arXiv:2506.07477, June 2025.

Petrovcic, J., et al. "Combining Textual and Structural Information for Premise Selection in Lean." arXiv:2510.23637, October 2025.

"PROOFWALA: Multilingual Proof Data Synthesis and Verification in Lean 4 and Coq." arXiv:2502.04671, 2025.

"RocqStar: Leveraging Similarity-driven Retrieval and Agentic Systems for Rocq Generation." arXiv:2505.22846, *AAMAS*, 2026.

Song, P., et al. "Lean Copilot: Large Language Models as Copilots for Theorem Proving in Lean." *International Conference on Learning Representations (ICLR)*, 2025.

Thompson, S., et al. "Rango: Adaptive Retrieval-Augmented Proving for Automated Software Verification." *International Conference on Software Engineering (ICSE)*, 2025. Distinguished Paper Award.

Yang, K., et al. "LeanDojo: Theorem Proving with Retrieval-Augmented Language Models." *Advances in Neural Information Processing Systems (NeurIPS)*, 2023.

Yang, K. and Deng, J. "Learning to Prove Theorems via Interacting with Proof Assistants." *International Conference on Machine Learning (ICML)*, 2019.

Zhu, R., et al. "Assisting Mathematical Formalization with A Learning-based Premise Retriever." arXiv:2501.13959, January 2025.

"LeanExplore: A Search Engine for Lean 4." arXiv:2506.11085, June 2025.

"REAL-Prover: Retrieval Augmented Lean Prover for Mathematical Reasoning." arXiv:2505.20613, May 2025.

Fang, Y., et al. "Scaling Laws for Dense Retrieval." *Proceedings of SIGIR*, 2024.
