# Custom Tokenization for Coq/Rocq Neural Premise Selection

## 1. Motivation

The neural premise selection system described in `neural-network.md` initializes from CodeBERT (microsoft/codebert-base), a 125M-parameter transformer pretrained on six programming languages. CodeBERT uses a RoBERTa-style Byte-Pair Encoding tokenizer with a 50,265-token vocabulary learned from English text and source code in Python, Java, JavaScript, PHP, Ruby, and Go. No formal proof assistant language appears in its pretraining corpus.

Research from the CFR system (Zhu et al., 2025) demonstrated that replacing a generic tokenizer with a custom WordPiece tokenizer trained on formal Lean 4 corpora produced a **+33% relative improvement in Recall@5** (38.20% vs 28.78%) over ReProver's byte-level ByT5 tokenizer — the single largest performance gain attributable to any individual design decision in that system, exceeding the impact of model architecture, training objective, or dataset size.

This document surveys the tokenization problem for Coq/Rocq, reviews approaches from the literature, and evaluates strategies for integrating a domain-specific tokenizer into the CodeBERT-based premise selection pipeline.

## 2. How Generic Tokenizers Fail on Coq Syntax

### 2.1 Over-Segmentation of Identifiers

CodeBERT's BPE tokenizer was trained on general-purpose programming languages where identifiers like `addElement` or `get_value` are common. Coq identifiers follow different conventions:

**Dot-qualified names.** Coq uses dot-separated module paths: `Coq.Init.Nat.add`, `mathcomp.algebra.ssralg.GRing`, `Stdlib.Lists.List.forall2_cons`. A generic tokenizer segments these into many subword tokens:

```
Nat.add_comm  →  [Nat, ., add, _, comm]           (5 tokens)
List.forall2  →  [List, ., for, all, 2]            (5 tokens)
mathcomp.algebra.ssralg  →  [math, comp, ., alg, ebra, ., ss, ral, g]  (9 tokens)
```

A domain-specific tokenizer could represent `Nat.add_comm` as 1–2 tokens and `ssralg` as a single token, reducing sequence length and preserving semantic units.

**Underscore-separated components.** Coq naming conventions use underscores extensively: `Nat.sub_add`, `Z.mul_comm`, `List.nth_error`. Generic tokenizers split on underscores, fragmenting semantically meaningful names.

**Prime suffixes.** Coq allows primes in identifiers (`x'`, `H'`, `IHn'`). Generic tokenizers may treat the prime as a separate token or merge it unpredictably.

### 2.2 Unicode Mathematical Symbols

Coq libraries use Unicode notation extensively:

| Symbol | Meaning | Frequency |
|--------|---------|-----------|
| `∀` (U+2200) | Universal quantification | Every goal |
| `→` (U+2192) | Function type / implication | Every goal |
| `∃` (U+2203) | Existential quantification | Common |
| `ℕ` (U+2115) | Natural numbers | Common in Stdlib |
| `ℤ` (U+2124) | Integers | Common in ZArith |
| `≤` (U+2264) | Less-than-or-equal | Common |
| `⊢` (U+22A2) | Turnstile (entailment) | Proof states |
| `⟨⟩` (U+27E8/9) | Angle brackets | MathComp |
| `⊆` (U+2286) | Subset | stdpp, MathComp |
| `∘` (U+2218) | Function composition | Various |

CodeBERT's vocabulary may represent these as unknown tokens or as multi-byte fallback sequences, losing semantic information. A domain-specific tokenizer includes these symbols as first-class vocabulary entries.

### 2.3 Coq-Specific Syntax Patterns

Several Coq constructs have no analogue in CodeBERT's pretraining languages:

**Scope delimiters.** `%N`, `%Z`, `%R` modify interpretation of notation — a generic tokenizer sees `%` as a modulo operator.

**SSReflect tacticals.** `move=>`, `apply/`, `/=`, `//`, `case/orP` — these are not operators in any of CodeBERT's pretraining languages.

**Sentence terminators.** In Coq, `.` terminates commands. A dot in `H.` is a sentence terminator, while in `Nat.add` it is a qualified name separator. Generic tokenizers cannot distinguish these.

**Notation brackets.** MathComp uses `[seq x <- s | P x]`, `[set x | P x]`, `[exists x, P x]` — bracket-delimited notation patterns unknown to generic tokenizers.

### 2.4 Sequence Length Impact

Coq proof states serialized for the bi-encoder (Section 3.4 of `neural-network.md`) include hypotheses with types and a goal type. With a 512-token limit, over-segmentation directly reduces the amount of proof state that fits in the context window. If a generic tokenizer uses 3–5x more tokens than necessary for Coq identifiers, complex proof states may be truncated, losing critical information.

## 3. Evidence from the Literature

### 3.1 CFR: Custom WordPiece for Lean (Zhu et al., 2025)

The Custom Formal-language Retriever (CFR) trained a WordPiece tokenizer with vocabulary size 30,522 on a corpus constructed by concatenating Lean 4 proof states and all premises' argument lists and goals from Mathlib4 v4.10.0 (149,549 premises, 65,567 training theorems).

The CFR model — a 6-layer BERT (12 heads, hidden 768, intermediate 3072) — achieved:

| Metric | CFR (custom tokenizer) | ReProver (ByT5 byte-level) | Relative improvement |
|--------|----------------------|--------------------------|---------------------|
| Recall@1 | 15.17% | 11.79% | +29% |
| Recall@5 | 38.20% | 28.78% | +33% |
| Recall@10 | 46.53% | 36.69% | +27% |
| nDCG@1 | 0.3731 | 0.3351 | +11% |

**Ablation (Table 4 of the paper).** Without the custom tokenizer, Recall@5 dropped from 25.81 to 20.49 and Recall@10 dropped from 37.70 to 30.33 — confirming that the domain-specific tokenizer accounts for a large share of the improvement. The paper states: "performance when k=5 or 10 degrades a lot" without it.

The paper also found that pre-training BERT from scratch on formal corpora yielded only modest gains over fine-tuning a pretrained checkpoint — the tokenizer was the critical ingredient, not from-scratch pretraining.

### 3.2 RocqStar: CodeBERT with Default Tokenizer on Coq (JetBrains, 2025)

RocqStar (AAMAS 2026) used CodeBERT with its **default RoBERTa tokenizer** on Coq/Rocq, achieving 28% relative improvement over Jaccard-based retrieval on the IMM-300 benchmark. Key details:

- Base: CodeBERT (microsoft/codebert-base), 125M parameters
- Max sequence length: 128 tokens
- Training: InfoNCE contrastive loss on BigRocq (76,524 statements)
- Also tested: `gte-modernbert-base` — no improvement over CodeBERT

RocqStar's results establish a baseline for what CodeBERT's default tokenizer achieves on Coq. The short max sequence length (128 tokens) may have masked tokenizer inefficiency — at 512 tokens, the penalty for over-segmentation would be more visible. The CFR ablation suggests a custom tokenizer could yield substantial additional gains.

### 3.3 Rango: BM25 Outperforms Dense Embeddings for Coq (Thompson et al., 2025)

Rango (ICSE 2025 Distinguished Paper) found that BM25 over proof states — treating formal identifiers as words — outperformed CodeBERT dense embeddings by **46%** for in-project Coq proof retrieval. This result is partially a tokenization story: BM25 treats `Nat.add_comm` as a single lexical unit, while CodeBERT fragments it into subword pieces that dilute the embedding signal. A domain-specific tokenizer that preserves identifier boundaries would narrow this gap.

### 3.4 Tokenization Findings Across Systems

| System | Tokenization | Key finding |
|--------|-------------|-------------|
| CFR (2025) | Custom WordPiece on Lean corpus | +33% Recall@5; tokenizer is the critical ingredient |
| ReProver (2023) | ByT5 byte-level (256 vocab) | No OOV issues but 4x sequence length; 299M params needed |
| LeanHammer (2025) | Standard NLP BPE | 82M params outperforms 299M ReProver — but via better data, not tokenizer |
| Lean Finder (2025) | DeepSeek-Prover tokenizer | Code-pretrained tokenizer handles Lean 4 naturally; 7B params |
| Magnushammer (2024) | The Pile BPE | Pre-trained on GitHub+arXiv; handles Isabelle syntax |

The consistent pattern: systems using generic tokenizers either (a) require larger models to compensate, (b) use byte-level encoding at a 4x length cost, or (c) rely on code-pretrained tokenizers that partially cover formal syntax. A domain-specific tokenizer is the most direct solution.

## 4. Coq/Rocq Corpus Characteristics

### 4.1 Target Libraries

The extraction pipeline (Section 3.1 of `neural-network.md`) targets six libraries:

| Library | Declarations | Proof style | Distinctive vocabulary |
|---------|-------------|-------------|----------------------|
| Stdlib | ~31,000 | Standard Ltac | `Nat.*`, `Z.*`, `List.*`, `Bool.*` |
| MathComp | ~58,000 | SSReflect | `ssralg.*`, `fingroup.*`, `perm.*`, boolean views |
| stdpp | ~5,000 | Iris-style Ltac | `gmap`, `coPset`, `excl`, `agree` |
| Flocq | ~2,600 | Ltac | `Fcore_*`, `Fprop_*`, `Raux.*` |
| Coquelicot | ~2,400 | Ltac | `Derive`, `RInt`, `locally`, `filterlim` |
| Interval | ~20,000 | Reflexive Ltac | `I.*`, `Xreal`, `Interval_*` |

### 4.2 Vocabulary Categories

A Coq tokenizer must handle several distinct vocabulary categories:

**Tactic names.** High-frequency tokens that should be single vocabulary entries:
`intro`, `apply`, `rewrite`, `destruct`, `induction`, `simpl`, `unfold`, `auto`, `lia`, `ring`, `field`, `omega`, `reflexivity`, `symmetry`, `transitivity`, `exact`, `assumption`, `trivial`, `discriminate`, `injection`, `inversion`, `subst`, `clear`, `rename`, `assert`, `pose`, `set`, `have`, `enough`, `specialize`

**SSReflect tactics** (MathComp-specific):
`move`, `case`, `elim`, `apply`, `rewrite`, `have`, `suff`, `wlog`, `congr`, `unlock` — plus tacticals `/=`, `//`, `//=`, `=>`, `/eqP`, `/andP`, `/orP`

**Gallina keywords:**
`Theorem`, `Lemma`, `Proposition`, `Corollary`, `Definition`, `Fixpoint`, `Inductive`, `Record`, `Class`, `Instance`, `Section`, `Module`, `Import`, `Require`, `Open`, `Scope`, `Notation`, `Proof`, `Qed`, `Admitted`, `Defined`

**Type constructors and common types:**
`nat`, `bool`, `list`, `option`, `prod`, `sum`, `Prop`, `Type`, `Set`, `unit`, `Empty_set`, `sigT`, `sig`, `eq`, `ex`, `and`, `or`, `not`, `True`, `False`

**Namespace prefixes** (high-frequency, should be preserved):
`Nat.`, `Z.`, `N.`, `Q.`, `R.`, `List.`, `Bool.`, `Pos.`, `String.`

**Library-specific identifiers** that a generic tokenizer fragments:
`ssreflect`, `ssrbool`, `ssrfun`, `ssrnat`, `fintype`, `bigop`, `perm`, `matrix`, `mxalgebra`

### 4.3 Coq Lexical Rules

Coq's lexical conventions (from the Rocq reference manual):
- `first_letter = a..z | A..Z | _ | unicode_letter`
- `subsequent_letter = first_letter | digit | ' | unicode_id_part`
- Unicode letters include Greek (`α`, `β`, `γ`, `δ`, `ε`), mathematical letter-like symbols, subscripts, and superscripts
- Identifiers are case-sensitive
- Dots are context-dependent: qualified name separator (`Nat.add`) vs. sentence terminator (`Qed.`)

### 4.4 Estimated Corpus Size

Combining the six target libraries:

| Source | Estimated LOC | Estimated unique tokens |
|--------|--------------|------------------------|
| Stdlib | ~150,000 | ~5,000 |
| MathComp | ~164,000 | ~8,000 |
| stdpp | ~50,000 | ~3,000 |
| Flocq | ~25,000 | ~2,000 |
| Coquelicot | ~18,000 | ~1,500 |
| Interval | ~10,000 | ~800 |
| **Total** | **~417,000** | **~12,000–15,000 unique** |

Additionally, proof state serializations from the extraction pipeline provide a complementary corpus: ~118K declarations producing ~130K (state, premise) pairs, each containing serialized goal types, hypothesis types, and premise statements.

## 5. Why Closed Vocabulary, Not Subword Tokenization

### 5.1 The Key Observation

Unlike natural language — where novel words appear constantly — Coq's vocabulary for any installed library set is **closed**. Every token that appears in a serialized proof state comes from one of four finite sources:

1. **Library declarations** (~118,000 across the six target libraries). Every lemma, definition, type, and notation is known at index time.
2. **Hypothesis variable names** (`n`, `m`, `H`, `H0`, `x`, `y`, `IHn`, etc.). A small, predictable set.
3. **Syntax tokens** (~50 keywords, ~30 tactics, ~20 punctuation characters).
4. **Unicode mathematical symbols** (~80 symbols including `∀`, `→`, `⊢`, Greek letters).

The total is approximately **150,000 distinct tokens**. There are no "unknown words" at inference time: the model only encodes identifiers from the indexed declaration corpus and the fixed syntax of the Calculus of Inductive Constructions.

Subword tokenization (WordPiece, BPE) was designed for open-vocabulary natural language, where the model must handle words never seen during training. In Coq, this problem does not exist for the base model. Subword decomposition adds complexity (regex pre-tokenizers, learned merge rules, subword ambiguity) to solve a problem that the domain does not have.

### 5.2 Subword Approaches Considered

The following subword algorithms were evaluated and rejected:

**WordPiece** (BERT, CodeBERT, CFR). CFR demonstrated +33% Recall@5 on Lean with a custom WordPiece tokenizer. However, CFR operated on Lean's Mathlib — a corpus of 149,549 premises, an order of magnitude larger than Coq's 6-library target. At Coq's scale, every identifier fits in the vocabulary directly without subword decomposition.

**Byte-Pair Encoding** (GPT, RoBERTa). CodeBERT's current tokenizer. Over-segments Coq identifiers as documented in Section 2.

**Byte-level** (ByT5, ReProver). Eliminates all tokenization engineering but imposes a 4x sequence length penalty, requiring larger models (299M+) to compensate.

**Byte Latent Transformer** (Meta, 2024). Requires a fundamentally different model architecture incompatible with BERT-class bi-encoders.

**SuperBPE** (COLM 2025). Designed for open-vocabulary language modeling with 200K+ token vocabularies. Not applicable at the scale of Coq libraries.

### 5.3 Why Not Train a Custom BPE on Coq Corpora?

The strongest counter-argument to a closed vocabulary is: "train BPE (or WordPiece) on Coq source code so that Coq identifiers become frequent merge pairs." CFR did exactly this for Lean and achieved +33% Recall@5. Why not do the same for Coq?

**The answer is that a custom BPE converges to the closed vocabulary at Coq's scale — but with worse properties.**

**1. At convergence, BPE rediscovers the closed vocabulary.** BPE learns merge rules by greedily combining the most frequent adjacent byte-pairs. On a corpus of ~417K lines of Coq where `Nat.add_comm` appears hundreds of times, BPE will eventually merge `N` + `a` + `t` + `.` + `a` + `d` + `d` + `_` + `c` + `o` + `m` + `m` into a single token — reproducing the closed vocabulary entry. With a vocabulary budget of ~150K tokens, essentially every high-frequency Coq identifier will end up as its own token. The subword decomposition machinery (merge tables, priority queues, regex pre-tokenization) exists only to arrive at the same result that a dictionary lookup achieves directly.

**2. BPE introduces ambiguity that the closed vocabulary avoids.** BPE tokenization is not bijective: the segmentation of a string depends on the learned merge order, and different training corpora produce different segmentations of the same input. If `Nat.add_comm` was rare in the training corpus (e.g., from a library version that added it late), BPE may segment it as `Nat.add` + `_comm` or `Nat` + `.add_comm` — different from the segmentation of `Nat.add` alone. The closed vocabulary eliminates this: `Nat.add_comm` is always token ID 9 (or whatever its assigned ID is), regardless of corpus frequency.

**3. BPE handles the tail poorly.** Even a custom BPE trained on Coq will fragment rare identifiers. Library-specific names like `Interval_missing_bisect` or `Fcore_Raux.bpow_lt_bpow` may not appear often enough in the training corpus to form complete merge pairs. These tail identifiers receive the worst tokenization — precisely the identifiers where retrieval is hardest and correct tokenization matters most. The closed vocabulary treats every declaration identically: one token, always.

**4. CFR's gains came from replacing a *generic* tokenizer, not from BPE itself.** CFR compared a custom WordPiece tokenizer against ByT5's byte-level tokenizer (256-token vocabulary, ~4x sequence length penalty) and CodeBERT's English+code BPE. The +33% gain demonstrates that domain-specific tokenization matters — not that WordPiece is the optimal algorithm. A closed vocabulary is an even more domain-specific tokenizer: it is the limit of what a perfect BPE would converge to, without the convergence process.

**5. CFR operated at a comparable scale.** Lean's Mathlib has 149,549 premises — similar to Coq's 6-library corpus (~118,000 declarations). At this scale, the closed vocabulary (~150K tokens) is larger than CodeBERT's original vocabulary (50,265 tokens), but still practical for a single embedding table.

**6. A trained tokenizer is not a derived artifact.** A BPE tokenizer's merge rules are learned from a training corpus and frozen at training time. If the library adds new identifiers (e.g., a MathComp update adds 500 new lemmas), the tokenizer cannot incorporate them without retraining. The closed vocabulary is rebuilt from the search index in seconds — it is a derived artifact that tracks the installed library state, not a trained model that must be versioned and distributed.

**In summary:** training a custom BPE on Coq would produce a tokenizer that (a) converges toward the closed vocabulary for frequent identifiers, (b) fragments rare identifiers that the closed vocabulary handles perfectly, (c) introduces segmentation ambiguity, (d) requires training infrastructure, and (e) must be retrained when libraries update. The closed vocabulary achieves the ceiling that BPE asymptotically approaches, with none of the complexity.

### 5.4 Advantages of Closed Vocabulary

| Property | Closed vocabulary | Subword (WordPiece/BPE) |
|----------|------------------|------------------------|
| Fertility | Always 1 token per identifier | 1–9 tokens depending on identifier |
| Tokenization speed | O(1) dictionary lookup | O(n) subword search |
| Implementation | Dictionary mapping | Regex pre-tokenizer + learned merge rules |
| Determinism | Bijective: each identifier ↔ exactly one token ID | Ambiguous: subword boundaries depend on merge order |
| Context window usage | Optimal — no wasted tokens | Up to 5x waste on dot-qualified names |
| Failure modes | [UNK] for unknown tokens | Fragmented embeddings for over-segmented identifiers |

### 5.5 Handling Unknown Tokens

The closed vocabulary maps unseen identifiers to `[UNK]`. In practice, this is rare: the vocabulary is built from the same declaration corpus that the model retrieves against, so every indexed premise has a token. `[UNK]` appears only for identifiers that are neither in the indexed libraries nor in the fixed token sets — an edge case limited to unusual proof state content.

**Library updates.** New library versions may add identifiers. The vocabulary is rebuilt whenever the search index is rebuilt (`poule build-vocabulary` runs as part of index construction), so the vocabulary tracks the installed library state. The vocabulary is a derived artifact, not a trained model.

## 6. Embedding Layer Integration

Replacing CodeBERT's 50,265-token BPE vocabulary with a ~150K-token closed vocabulary requires reinitializing the embedding layer.

**Procedure:**

1. Build the closed vocabulary from the search index (Section 7).
2. Load CodeBERT's transformer layers (layers 1–12) with pretrained weights.
3. Create a new `nn.Embedding(vocab_size, 768)` sized to the closed vocabulary.
4. Initialize embeddings: for tokens that overlap with CodeBERT's original vocabulary (digits, punctuation, common English words like `nat`, `list`, `bool`), copy the pretrained embedding. For Coq-specific tokens (`Nat.add_comm`, `ssreflect`, `∀`), initialize randomly (normal distribution, σ = 0.02).
5. Fine-tune the full model with masked contrastive loss on Coq training data.

CodeBERT's 12 transformer layers retain their full pretrained weights — only the embedding layer is partially cold. The CFR paper found that the tokenizer mattered more than pretraining, and contrastive fine-tuning provides sufficient signal for the embeddings to converge.

**Embedding table size.** At ~150K tokens × 768 dimensions: ~440 MB (FP32) or ~110 MB (INT8). This is larger than CodeBERT's original 50,265-token table (~147 MB FP32), but the tradeoff is justified by perfect tokenization fertility (1 token per identifier, always).

## 7. Vocabulary Construction

### 7.1 Sources

The vocabulary is constructed from two sources:

**Source 1: The search index.** All declarations in `index.db` provide the complete set of library identifiers — fully-qualified names like `Nat.add_comm`, `List.forall2_cons`, `mathcomp.algebra.ssralg.GRing.mul`. This is the authoritative source for premise identifiers.

**Source 2: Serialized proof states.** The training data extraction pipeline produces serialized proof states that contain hypothesis variable names, type expressions, and goal types. Scanning these captures the variable name vocabulary (`n`, `m`, `H`, `H0`, `x`, `y`, `IHn'`, etc.) and any syntax tokens that appear in the model's actual input distribution.

### 7.2 Fixed Token Sets

In addition to identifiers extracted from the corpus, the vocabulary includes fixed token sets:

**Special tokens:** `[PAD]`, `[UNK]`, `[CLS]`, `[SEP]`, `[MASK]`

**Punctuation and delimiters:** `(`, `)`, `{`, `}`, `[`, `]`, `:`, `;`, `,`, `.`, `|`, `@`, `!`, `?`, `_`, `'`, `#`, `=`, `+`, `-`, `*`, `/`, `<`, `>`, `~`

**SSReflect tacticals:** `/=`, `//`, `//=`, `=>`, `->`, `<-`

**Scope delimiters:** `%N`, `%Z`, `%R`, `%Q`, `%positive`, `%type`

**Unicode mathematical symbols:**
`∀`, `∃`, `→`, `←`, `↔`, `⊢`, `⊣`, `≤`, `≥`, `≠`, `≡`, `∧`, `∨`, `¬`, `⊆`, `⊇`, `∈`, `∉`, `⊂`, `⊃`, `∪`, `∩`, `∘`, `×`, `⊕`, `⊗`, `ℕ`, `ℤ`, `ℚ`, `ℝ`, `ℂ`

**Greek letters:**
`α`, `β`, `γ`, `δ`, `ε`, `ζ`, `η`, `θ`, `ι`, `κ`, `λ`, `μ`, `ν`, `ξ`, `π`, `ρ`, `σ`, `τ`, `υ`, `φ`, `χ`, `ψ`, `ω`, `Γ`, `Δ`, `Θ`, `Λ`, `Ξ`, `Π`, `Σ`, `Φ`, `Ψ`, `Ω`

**Numeric tokens:** `0`–`9` as individual digits, plus multi-digit numbers observed in the corpus.

### 7.3 Tokenization Procedure

```
1. Apply NFC Unicode normalization
2. Split on whitespace
3. For each token: look up in vocabulary dict → token ID (or [UNK] ID)
4. Prepend [CLS], append [SEP]
5. Pad/truncate to max_length=512
```

No regex pre-tokenizer. No subword search. O(1) dictionary lookup per token.

The proof state serialization format (Section 3.1 of `neural-network.md`) already uses whitespace to separate tokens — hypotheses are `name : type` on separate lines, and types use spaces around operators. Whitespace splitting aligns naturally with this format.

### 7.4 Vocabulary File Format

The vocabulary is stored as a JSON file mapping tokens to integer IDs:

```json
{
  "[PAD]": 0,
  "[UNK]": 1,
  "[CLS]": 2,
  "[SEP]": 3,
  "[MASK]": 4,
  "∀": 5,
  "→": 6,
  ":": 7,
  "nat": 8,
  "Nat.add_comm": 9,
  ...
}
```

### 7.5 Normalization

Apply **NFC (Canonical Decomposition + Canonical Composition)** Unicode normalization before tokenization. This ensures that precomposed characters (e.g., `é` as U+00E9) and decomposed sequences (e.g., `e` + `́` as U+0065 U+0301) are treated identically. Coq source files may use either form depending on the editor.

### 7.6 Expected Vocabulary Size

| Category | Estimated count |
|----------|----------------|
| Library identifiers (6 libraries) | ~118,000 |
| Training data tokens (variable names, syntax fragments) | ~33,000 |
| Fixed tokens (punctuation, tacticals, scope delimiters, digits) | ~110 |
| Unicode symbols + Greek letters | 64 |
| Special tokens | 5 |
| **Total** | **~150,000** |

## 8. Evaluation

### 8.1 Intrinsic Vocabulary Metrics

**[UNK] rate.** The percentage of tokens in held-out proof states that map to `[UNK]`. Target: **<1%**. Since the vocabulary is constructed from the same libraries used for training, this should be near 0% for the base model. Measure on the test split to verify.

**Sequence length.** Mean token count for serialized proof states. Compare against CodeBERT's default tokenizer. The closed vocabulary achieves perfect fertility (1 token per identifier), so sequence lengths should be **40–60% shorter** than with CodeBERT's BPE.

| Input | CodeBERT BPE (expected) | Closed vocabulary (expected) |
|-------|------------------------|------------------------------|
| `Nat.add_comm` | 5 tokens | 1 token |
| `ssreflect` | 3 tokens | 1 token |
| `List.forall2_cons` | 6 tokens | 1 token |
| `∀ n : nat, n + 0 = n` | ~8 tokens | 7 tokens |
| Typical proof state (5 hypotheses + goal) | ~80–120 tokens | ~30–50 tokens |

### 8.2 Extrinsic Retrieval Metrics

The ultimate evaluation is retrieval quality on the held-out test split (Section 3.2 of `neural-network.md`):

| Metric | Baseline (default tokenizer) | Target (closed vocabulary) |
|--------|-------|--------|
| Recall@1 | TBD | ≥ +20% relative |
| Recall@10 | TBD | ≥ +25% relative |
| Recall@32 | TBD | ≥ +15% relative |
| MRR | TBD | ≥ +15% relative |

These targets are conservative relative to CFR's +33% Recall@5, accounting for differences between Lean and Coq corpora.

### 8.3 Ablation Protocol

To isolate the vocabulary's contribution, compare:

1. **CodeBERT + default BPE tokenizer** — baseline.
2. **CodeBERT + closed vocabulary** — reinitialize embeddings, same fine-tuning procedure.

Both configurations use identical training data, hyperparameters, and evaluation splits. The only variable is the tokenizer and embedding initialization.

## 9. Risks and Mitigations

**Risk: Library updates add identifiers not in the vocabulary.** A new version of MathComp might add lemmas absent from the vocabulary.
**Mitigation:** The vocabulary is a derived artifact rebuilt whenever the search index is rebuilt. Running `poule build-vocabulary` after installing updated libraries produces a vocabulary that matches the current library state.

**Risk: Embedding reinitialization loses pretrained knowledge.** CodeBERT's transformer layers may depend on embedding-layer patterns that break with a new vocabulary.
**Mitigation:** Copy embeddings for overlapping tokens (digits, punctuation, common English words like `nat`, `list`, `bool`). Monitor validation loss during early fine-tuning — if it fails to decrease within the first epoch, investigate whether more aggressive embedding initialization (e.g., FOCUS) is needed.

**Risk: Whitespace splitting misaligns with proof state format.** Some proof state serializations may contain multi-word expressions that should be single tokens.
**Mitigation:** The serialization format in Section 3.1 of `neural-network.md` is deterministic and whitespace-delimited by design. Validate on 100+ serialized proof states that whitespace splitting produces the expected token sequence.

## 10. Implementation Sequence

1. **Vocabulary extraction.** Scan declarations from the search index and serialized proof states from the extraction pipeline. Collect all unique identifiers and syntax tokens.
2. **Vocabulary file generation.** Merge extracted identifiers with fixed token sets (special tokens, punctuation, Unicode symbols). Assign sequential integer IDs. Write the vocabulary JSON file.
3. **Intrinsic evaluation.** Measure [UNK] rate and sequence length on the test split (Section 8.1).
4. **Model integration.** Load CodeBERT, replace the embedding layer, copy overlapping embeddings, initialize new embeddings randomly.
5. **Contrastive fine-tuning.** Train with masked contrastive loss using the procedure from `neural-network.md`.
6. **Extrinsic evaluation.** Compare retrieval metrics against default-tokenizer baseline (Section 8.2).

## References

Zhu, R., et al. "Assisting Mathematical Formalization with A Learning-based Premise Retriever." arXiv:2501.13959, January 2025.
