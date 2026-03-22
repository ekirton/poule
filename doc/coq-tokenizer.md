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

| Library | Estimated theorems | Proof style | Distinctive vocabulary |
|---------|-------------------|-------------|----------------------|
| Stdlib | ~8,000 | Standard Ltac | `Nat.*`, `Z.*`, `List.*`, `Bool.*` |
| MathComp | ~15,000 | SSReflect | `ssralg.*`, `fingroup.*`, `perm.*`, boolean views |
| stdpp | ~5,000 | Iris-style Ltac | `gmap`, `coPset`, `excl`, `agree` |
| Flocq | ~3,000 | Ltac | `Fcore_*`, `Fprop_*`, `Raux.*` |
| Coquelicot | ~2,000 | Ltac | `Derive`, `RInt`, `locally`, `filterlim` |
| Interval | ~1,000 | Reflexive Ltac | `I.*`, `Xreal`, `Interval_*` |

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

Additionally, proof state serializations from the extraction pipeline provide a complementary corpus: ~34,000 theorems producing ~15,000+ (state, premise) pairs, each containing serialized goal types, hypothesis types, and premise statements.

## 5. Tokenizer Algorithm Options

### 5.1 WordPiece

**Used by:** BERT, CodeBERT, CFR

WordPiece builds a vocabulary by iteratively merging character pairs that maximize the likelihood of the training corpus. Subword tokens use a `##` prefix to indicate continuation (e.g., `ssreflect` → `ss`, `##reflect` if not in vocabulary).

| Attribute | Value |
|-----------|-------|
| Typical vocab size | 28,000–32,000 |
| Subword prefix | `##` (configurable) |
| OOV handling | Falls back to character-level |
| Unicode support | Full, via `initial_alphabet` parameter |
| Training speed | Fast (minutes on 400K LOC) |

**Advantages for Coq:** Direct precedent from CFR (+33% on Lean); compatible with BERT-class models; the `initial_alphabet` parameter can force-include all Unicode math symbols.

**Disadvantages:** Cannot learn cross-word patterns (e.g., `rewrite ->` as a unit); whitespace-delimited pre-tokenization may not align with Coq's syntax.

### 5.2 Byte-Pair Encoding (BPE)

**Used by:** GPT, RoBERTa (CodeBERT's current tokenizer), Magnushammer

BPE iteratively merges the most frequent byte/character pairs. RoBERTa uses byte-level BPE where the base vocabulary is 256 bytes, ensuring no OOV tokens.

| Attribute | Value |
|-----------|-------|
| Typical vocab size | 30,000–50,000 |
| Subword prefix | None (uses Ġ for space-preceded tokens in RoBERTa) |
| OOV handling | None (byte fallback) |
| Unicode support | Via UTF-8 byte sequences |

**Advantages:** No OOV tokens; CodeBERT already uses BPE, so swapping to a domain-specific BPE would be architecturally seamless.

**Disadvantages:** Byte-level BPE can produce unintuitive subword boundaries for formal syntax; the `Ġ` (space) prefix convention doesn't align with Coq's dot-separated namespaces.

### 5.3 Byte-Level (ByT5)

**Used by:** ReProver (299M params)

Operates directly on UTF-8 bytes with a fixed 256-token vocabulary plus special tokens.

| Attribute | Value |
|-----------|-------|
| Vocab size | 259 (256 bytes + 3 special) |
| OOV handling | Impossible (all bytes are in vocabulary) |
| Sequence length | ~4x longer than token-level |

**Advantages:** Zero tokenization engineering; handles any Unicode symbol; no domain adaptation needed.

**Disadvantages:** 4x sequence length penalty (512 bytes ≈ 128 tokens of content); ReProver needed 299M parameters partly to compensate for this overhead; incompatible with efficient CPU inference at <10ms.

### 5.4 Byte Latent Transformer (BLT)

**Source:** Meta, December 2024

BLT uses entropy-based dynamic patching: high-entropy regions (rare words, code, numbers) receive smaller patches (more compute), while low-entropy regions (common words) receive larger patches (fewer tokens). Matches Llama 3 at 8B scale with up to 50% fewer inference FLOPs.

**Relevance to Coq:** Conceptually appealing — formal syntax is high-entropy and would receive fine-grained attention. However, BLT requires a fundamentally different model architecture (three-component: local encoder, latent transformer, local decoder) that is incompatible with BERT-class bi-encoders. No integration libraries exist. **Not applicable for this project.**

### 5.5 SuperBPE

**Source:** COLM 2025

Two-pass BPE: Stage 1 learns subwords with whitespace pre-tokenization up to a transition point; Stage 2 disables pre-tokenization to learn cross-word "superword" tokens. Achieves 33% fewer tokens at 200K vocab; +4.0% absolute across 30 NLP tasks; +8.2% on MMLU.

**Relevance to Coq:** Mixed results on code tasks (HumanEval -2.5%, MBPP +0.8%). The cross-word superword learning could capture patterns like `rewrite ->` or `apply H.` as units, but the whitespace-centric assumptions don't align well with Coq's syntax where dots and brackets serve as delimiters. The 200K vocabulary target is far larger than the ~30K used by BERT-class models. **Monitoring only; not recommended for initial implementation.**

### 5.6 Recommendation

**WordPiece** is the recommended algorithm, for three reasons:
1. Direct precedent: CFR demonstrated +33% improvement on formal math with WordPiece.
2. Compatibility: CodeBERT is a BERT-class model; WordPiece is the native tokenizer format.
3. Simplicity: HuggingFace `tokenizers` library provides production-quality WordPiece training.

## 6. Integration Strategies

Replacing CodeBERT's tokenizer creates a vocabulary mismatch: the pretrained embedding layer maps 50,265 token IDs to 768-dimensional vectors, but a new tokenizer produces a different set of token IDs. Three strategies address this.

### 6.1 Strategy A: New Tokenizer + Reinitialize Embeddings

Train a custom tokenizer, create a new embedding layer sized to the new vocabulary, and initialize embeddings randomly (or with a targeted scheme). Fine-tune from this state.

**Procedure:**
1. Train WordPiece tokenizer on Coq corpus (Section 7).
2. Load CodeBERT's transformer layers (layers 1–12) with pretrained weights.
3. Replace the embedding layer with a new `nn.Embedding(new_vocab_size, 768)`.
4. Initialize new embeddings: for tokens that overlap with the old vocabulary, copy the old embedding; for new tokens, initialize randomly (normal distribution, σ = 0.02).
5. Fine-tune the full model with contrastive loss on Coq training data.

**Cost:** Standard fine-tuning time (~6.5 GPU-days on A6000, matching LeanHammer).
**Risk:** Loss of CodeBERT's pretrained knowledge in the embedding layer. The transformer layers retain their pretrained attention patterns, but the embedding layer starts partially cold.

### 6.2 Strategy B: Vocabulary Extension

Keep CodeBERT's existing 50,265 tokens and add Coq-specific tokens. Resize the embedding layer and initialize new token embeddings.

**Procedure:**
1. Identify high-value Coq tokens not in CodeBERT's vocabulary (e.g., `∀`, `⊢`, `ssreflect`, `Nat.add_comm`).
2. Add them via `tokenizer.add_tokens(new_tokens)`.
3. Resize model embeddings: `model.resize_token_embeddings(len(tokenizer))`.
4. New token embeddings are initialized randomly; existing embeddings are preserved.
5. Fine-tune.

**Cost:** Minimal additional cost over standard fine-tuning.
**Risk:** The extended vocabulary still uses CodeBERT's BPE pre-tokenization rules, which may split Coq identifiers before the new tokens can match. For example, if `Nat.add_comm` is added as a token but BPE pre-tokenization splits on `.` before vocabulary lookup, the new token is never activated. This approach works for symbols (`∀`, `→`) but not for complex identifiers.

### 6.3 Strategy C: FOCUS Embedding Initialization

FOCUS (Dobler and Schütze, EMNLP 2023) provides a principled method for initializing embeddings when replacing a tokenizer. It uses fastText embeddings trained on the target domain to compute weighted averages of overlapping old-vocabulary tokens for each new-vocabulary token.

**Procedure:**
1. Train custom WordPiece tokenizer on Coq corpus.
2. Train fastText embeddings on the same Coq corpus.
3. For each new token, find its representation as a weighted combination of old-vocabulary tokens using sparsemax over fastText similarity scores.
4. Initialize the new embedding layer using these weighted combinations.
5. Fine-tune the full model.

**Cost:** Additional step of training fastText (~minutes on 400K LOC), plus standard fine-tuning.
**Risk:** FOCUS was designed for natural language domain adaptation. Its effectiveness on formal mathematical syntax — where token semantics differ fundamentally from natural language — is unvalidated.

### 6.4 Strategy D: Train Tokenizer + Full Continued Pretraining

Train a custom tokenizer, reinitialize the embedding layer, and perform continued masked language model (MLM) pretraining on Coq corpora before fine-tuning for retrieval.

**Procedure:**
1. Train custom WordPiece tokenizer on Coq corpus.
2. Reinitialize embedding layer (as in Strategy A).
3. Perform continued MLM pretraining on Coq `.v` files + serialized proof states.
4. Fine-tune for retrieval with contrastive loss.

**Cost:** Additional pretraining step. Research (Gogoulou et al., 2024) suggests **50 billion tokens minimum** for full recovery after tokenizer swapping — far beyond the ~400K LOC Coq corpus. However, this finding is for general-purpose models; domain-specific recovery on a small, focused domain may require less data.
**Risk:** The Coq corpus (~400K LOC) is too small for meaningful MLM pretraining. The CFR paper found that "pre-training on formal corpus alone yields limited gains" — the tokenizer mattered more than pre-training.

### 6.5 Comparison

| Strategy | Embedding init quality | Pretrained knowledge retained | Additional cost | Complexity |
|----------|----------------------|------------------------------|----------------|------------|
| A: Reinitialize | Low (random for new tokens) | Transformer layers only | None | Low |
| B: Extend vocab | High (existing tokens preserved) | Full (but BPE pre-tokenization unchanged) | None | Low |
| C: FOCUS | Medium (weighted old-token combos) | Transformer layers + partial embedding transfer | fastText training | Medium |
| D: Continued pretraining | Highest (after convergence) | Full (after recovery) | MLM pretraining | High |

### 6.6 Recommendation

**Strategy A (reinitialize embeddings)** is recommended as the starting point, for three reasons:

1. **CFR precedent.** CFR trained BERT from scratch with a custom tokenizer and achieved the best results. Their ablation showed the tokenizer mattered more than pre-training, suggesting that a partially-reinitialized model with good fine-tuning data will converge to strong performance.

2. **Simplicity.** No additional dependencies (fastText, extended pretraining corpus) are required.

3. **Overlap copying.** Tokens that exist in both the old and new vocabularies (common English words, digits, punctuation) can have their embeddings copied directly, preserving some pretrained knowledge. The transformer layers (12 layers, 768 hidden) retain their full pretrained attention patterns.

If Strategy A underperforms relative to the default-tokenizer baseline, Strategy C (FOCUS) is the natural next step.

## 7. Training Procedure

### 7.1 Corpus Construction

The training corpus for the tokenizer combines two sources:

**Source 1: Raw Coq source files.** All `.v` files from the six target libraries (Stdlib, MathComp, stdpp, Flocq, Coquelicot, Interval), totaling ~417,000 LOC. These provide coverage of Gallina syntax, tactic scripts, notations, and comments.

**Source 2: Serialized proof states.** The proof state serializations produced by the extraction pipeline (Section 3.1 of `neural-network.md`) — the same text the model will see at inference time. These contain hypothesis names, types, and goal types in the deterministic serialization format. Including these ensures the tokenizer's vocabulary is optimized for the actual model input distribution, not just raw source code.

Both sources should be included because the model processes serialized proof states (not raw `.v` files) at inference time, but the `.v` files provide broader vocabulary coverage for premise statements.

### 7.2 Pre-Tokenization

Coq's syntax requires a custom pre-tokenizer that respects:

1. **Whitespace splitting.** Standard whitespace boundaries.
2. **Dot-qualified names preserved.** `Nat.add_comm` should be kept as a single pre-token so WordPiece can learn it as one or two subwords, not five.
3. **Sentence-terminating dots split.** A dot followed by whitespace or EOF is a sentence terminator and should be a separate token.
4. **Unicode symbols as individual tokens.** `∀`, `→`, `∃`, `⊢` should each be a single pre-token.
5. **SSReflect tacticals preserved.** `/=`, `//`, `//=`, `=>` should be single pre-tokens.
6. **Scope delimiters preserved.** `%N`, `%Z`, `%R` should be single pre-tokens.

A regex-based pre-tokenizer can implement these rules:

```python
import re

COQ_PRE_TOKENIZE = re.compile(r"""
    [A-Za-z_\u0370-\u03FF\u1D00-\u1DBF]     # identifier start
    [A-Za-z0-9_'\u0370-\u03FF\u1D00-\u1DBF]* # identifier body
    (?:\.[A-Za-z_][A-Za-z0-9_']*)*            # dot-qualified continuation
  | //=? | /=                                  # ssreflect tacticals
  | =>                                         # ssreflect arrow
  | ->                                         # ASCII arrow
  | <-                                         # reverse arrow
  | %[A-Za-z]+                                 # scope delimiters
  | \.\s                                       # sentence terminator (dot + space)
  | \.(?=$)                                    # sentence terminator (dot at end)
  | [∀∃→←↔⊢⊣≤≥≠≡∧∨¬⊆⊇∈∉⊂⊃∪∩∘×⊕⊗ℕℤℚℝℂ]     # unicode math symbols
  | \d+                                        # numbers
  | \S                                         # any other non-whitespace character
""", re.VERBOSE | re.UNICODE)

def coq_pre_tokenize(text: str) -> list[str]:
    return COQ_PRE_TOKENIZE.findall(text)
```

### 7.3 WordPiece Training Configuration

```python
from tokenizers import Tokenizer
from tokenizers.models import WordPiece
from tokenizers.trainers import WordPieceTrainer
from tokenizers.pre_tokenizers import PreTokenizer

tokenizer = Tokenizer(WordPiece(unk_token="[UNK]"))

trainer = WordPieceTrainer(
    vocab_size=32768,
    min_frequency=2,
    special_tokens=["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"],
    initial_alphabet=[
        # Force-include Unicode math symbols
        "∀", "∃", "→", "←", "↔", "⊢", "⊣",
        "≤", "≥", "≠", "≡", "∧", "∨", "¬",
        "⊆", "⊇", "∈", "∉", "⊂", "⊃",
        "∪", "∩", "∘", "×", "⊕", "⊗",
        "ℕ", "ℤ", "ℚ", "ℝ", "ℂ",
        "α", "β", "γ", "δ", "ε", "ζ", "η", "θ",
        "ι", "κ", "λ", "μ", "ν", "ξ", "π", "ρ",
        "σ", "τ", "υ", "φ", "χ", "ψ", "ω",
        "Γ", "Δ", "Θ", "Λ", "Ξ", "Π", "Σ", "Φ", "Ψ", "Ω",
    ],
    continuing_subword_prefix="##",
)

# Custom pre-tokenizer wrapping the regex above
tokenizer.pre_tokenizer = PreTokenizer.custom(CoqPreTokenizer())

# Train on corpus
tokenizer.train_from_iterator(corpus_iterator(), trainer=trainer)
tokenizer.save("coq-wordpiece-32k.json")
```

### 7.4 Vocabulary Size Rationale

**32,768 tokens** (2^15), chosen based on:

1. **Domain precedent.** CFR used 30,522 for Lean. SciBERT used 31,000 for scientific text. PubMedBERT used 30,522 for biomedical text. The 28K–32K range is well-established for domain-specific BERT models.

2. **Corpus coverage.** With ~12,000–15,000 unique identifiers across the six libraries, a 32K vocabulary provides room for subword entries, Unicode symbols, and common English words (for comments and informal descriptions) while remaining compact.

3. **Embedding layer size.** At 768 dimensions, the embedding matrix is 32,768 × 768 × 4 bytes = ~96 MB (FP32) or ~24 MB (INT8). This is negligible compared to the transformer layers.

4. **Research on vocab size.** Studies on domain-specific BERTs (BioVocabBERT, 2023) found that vocabulary sizes from 30K to 80K produce nearly identical downstream performance — training data quality dominates. The 32K choice is conservative and well-supported.

### 7.5 Normalization

Apply **NFC (Canonical Decomposition + Canonical Composition)** Unicode normalization before tokenization. This ensures that precomposed characters (e.g., `é` as U+00E9) and decomposed sequences (e.g., `e` + `́` as U+0065 U+0301) are treated identically. Coq source files may use either form depending on the editor.

## 8. Evaluation

### 8.1 Intrinsic Tokenizer Metrics

Before model training, evaluate the tokenizer itself:

**Fertility** (tokens per identifier). Measure mean and p95 tokens-per-identifier on a held-out set of Coq declarations. A good domain tokenizer should represent common identifiers in 1–2 tokens.

| Identifier | Generic BPE (expected) | Custom WordPiece (target) |
|------------|----------------------|--------------------------|
| `Nat.add_comm` | 5 | 1–2 |
| `ssreflect` | 3 | 1 |
| `List.forall2_cons` | 6 | 2–3 |
| `∀ n : nat, n + 0 = n` | ~8 | ~6 |

**Coverage.** Percentage of Coq identifiers representable as a single token. Target: >80% of the 500 most frequent identifiers.

**Sequence length.** Mean token count for serialized proof states. Target: ≤70% of generic tokenizer's count, ensuring more proof state fits within the 512-token window.

### 8.2 Extrinsic Retrieval Metrics

The ultimate evaluation is retrieval quality on the held-out test split (Section 3.2 of `neural-network.md`):

| Metric | Baseline (default tokenizer) | Target (custom tokenizer) |
|--------|-------|--------|
| Recall@1 | TBD | ≥ +20% relative |
| Recall@10 | TBD | ≥ +25% relative |
| Recall@32 | TBD | ≥ +15% relative |
| MRR | TBD | ≥ +15% relative |

These targets are conservative relative to CFR's +33% Recall@5, accounting for differences between Lean and Coq corpora.

### 8.3 Ablation Protocol

To isolate the tokenizer's contribution, compare:

1. **CodeBERT + default tokenizer** — the current design baseline.
2. **CodeBERT + custom tokenizer (Strategy A)** — reinitialize embeddings, same fine-tuning procedure.
3. **CodeBERT + custom tokenizer (Strategy C)** — FOCUS initialization, same fine-tuning.

All three configurations use identical training data, hyperparameters, and evaluation splits. The only variable is the tokenizer and embedding initialization.

## 9. Risks and Mitigations

**Risk: Custom tokenizer underperforms on premise statements.** Premise statements contain Gallina type expressions, not proof states. If the tokenizer is trained primarily on proof states, it may over-optimize for tactic vocabulary at the expense of type-level expressions.
**Mitigation:** Include both raw `.v` files and serialized proof states in the training corpus (Section 7.1).

**Risk: Embedding reinitialization loses too much pretrained knowledge.** CodeBERT's transformer layers may depend on embedding-layer patterns that break with a new vocabulary.
**Mitigation:** Copy embeddings for overlapping tokens (Section 6.1). Monitor validation loss during early fine-tuning — if it fails to decrease within the first epoch, fall back to Strategy C (FOCUS).

**Risk: Small corpus produces a degenerate tokenizer.** 417K LOC may be insufficient for stable vocabulary learning, producing overly specific tokens.
**Mitigation:** Set `min_frequency=2` to prune rare subwords. Validate fertility metrics (Section 8.1) before committing to model training.

**Risk: Pre-tokenizer regex is fragile.** Complex regex rules for Coq syntax may mishandle edge cases (nested comments, string literals, unusual notations).
**Mitigation:** Unit-test the pre-tokenizer on a curated set of 100+ Coq snippets covering all six libraries and proof style families.

## 10. Implementation Sequence

1. **Corpus collection.** Extract `.v` files from the six target libraries; collect serialized proof states from the extraction pipeline.
2. **Pre-tokenizer implementation.** Implement and test the regex-based Coq pre-tokenizer.
3. **Tokenizer training.** Train WordPiece tokenizer (32,768 vocab) using HuggingFace `tokenizers` library.
4. **Intrinsic evaluation.** Measure fertility, coverage, and sequence length (Section 8.1).
5. **Model integration.** Load CodeBERT, replace tokenizer and embedding layer, copy overlapping embeddings.
6. **Contrastive fine-tuning.** Train with masked contrastive loss using the procedure from `neural-network.md`.
7. **Extrinsic evaluation.** Compare retrieval metrics against default-tokenizer baseline (Section 8.2).

## References

Dobler, K. and Schütze, H. "FOCUS: Effective Embedding Initialization for Monolingual Specialization of Multilingual Models." *EMNLP*, 2023.

Gogoulou, E., et al. "Getting the Most Out of Your Tokenizer for Pre-Training and Domain Adaptation." arXiv:2402.01035, 2024.

Li, Y., et al. "BioVocabBERT: How Robust Are Biomedical Pretrained Models to Vocabulary Changes?" arXiv:2306.17649, 2023.

Minixhofer, B., Ponti, E., and Vulić, I. "WECHSEL: Effective Initialization of Subword Embeddings for Cross-Lingual Transfer of Monolingual Representations." *NAACL*, 2022.

Zhu, R., et al. "Assisting Mathematical Formalization with A Learning-based Premise Retriever." arXiv:2501.13959, January 2025.
