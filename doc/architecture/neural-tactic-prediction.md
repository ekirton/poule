# Neural Tactic Prediction

Technical design for the tactic family classifier: model architecture, inference pipeline, and integration into the `suggest_tactics` MCP tool.

**Feature**: [Neural Tactic Prediction](../features/neural-tactic-prediction.md), [Pre-trained Model](../features/pre-trained-model.md)

---

## Component Diagram

```
Trained model (tactic-predictor.onnx) + Label map (tactic-labels.json)
  │
  │ loaded at server startup (when available)
  ▼
TacticPredictor
  │
  │ predict(proof_state_text) → top-K tactic families
  ▼
tactic_suggest()
  │
  │ merge neural predictions with rule-based suggestions
  ▼
suggest_tactics MCP tool response
```

## TacticPredictor

The `TacticPredictor` class loads a quantized ONNX tactic classifier and provides inference:

```
class TacticPredictor:
    model_path: Path          # tactic-predictor.onnx (INT8 ONNX)
    label_names: list[str]    # ordered tactic family names
    tokenizer: CoqTokenizer   # closed-vocabulary tokenizer

    predict(proof_state_text, top_k=5) → list[(family_name, confidence)]
```

**Inference pipeline:**
1. Tokenize proof state text using the closed-vocabulary tokenizer (whitespace split + dictionary lookup)
2. Pad/truncate to 512 tokens
3. Run ONNX session: input `[1, 512]` → output logits `[1, num_classes]`
4. Apply softmax to logits → probability distribution over tactic families
5. Return top-K families with their probabilities

**Availability check:** The predictor is available when (1) the ONNX model file exists, (2) the label map file exists, and (3) the vocabulary file exists. If any condition fails, `suggest_tactics` falls back to rule-based suggestions only.

## Integration with suggest_tactics

The existing `tactic_suggest()` function in `src/Poule/tactics/suggest.py` provides rule-based suggestions based on structural goal classification. Neural predictions are layered on top:

1. If `TacticPredictor` is available, call `predict(proof_state_text, top_k=5)`
2. Generate rule-based suggestions from goal structure (existing behavior)
3. Merge: neural predictions first (sorted by confidence), then rule-based suggestions not already covered
4. Return combined list as `list[TacticSuggestion]`

The MCP tool interface (`suggest_tactics`) is unchanged — the response format is the same regardless of whether neural predictions are included.

## Model Architecture (Training-Time)

See [neural-training.md](neural-training.md) for the training pipeline design.

The model is an encoder + classification head:
- **Encoder**: CodeBERT (microsoft/codebert-base), 125M parameters, with closed-vocabulary embedding layer
- **Pooling**: Mean pooling over non-padding tokens
- **Classification head**: `nn.Linear(768, num_classes)` mapping to ~30 tactic families
- **Output**: Logits `[B, num_classes]`

At inference time, only the quantized ONNX export is used. The PyTorch model is used during training only.

## Model Assets

| Asset | Format | Size | Purpose |
|-------|--------|------|---------|
| `tactic-predictor.onnx` | INT8 ONNX | ~25MB | Quantized classifier for CPU inference |
| `tactic-labels.json` | JSON list | <1KB | Ordered tactic family names (index → name) |
| `coq-vocabulary.json` | JSON dict | ~3MB | Closed-vocabulary tokenizer (token → ID) |

These assets are standalone — they are **not** part of the search index (`index.db`). They do not participate in library indexing or RRF fusion.

## Tactic Argument Retrieval

For tactic families that take lemma arguments, the argument retrieval layer queries the existing retrieval pipeline to find specific candidates. This produces full tactic suggestions (e.g., `apply Nat.add_comm`) instead of bare family names.

### Component Diagram

```
TacticPredictor.predict(proof_state_text)
  │
  │ → [(family_name, confidence), ...]
  ▼
ArgumentRetriever.retrieve(family_name, goal, hypotheses, pipeline_context)
  │
  │ Routes to retrieval strategy based on tactic family:
  │   apply/exact → search_by_type(goal.type)
  │   rewrite     → search_by_type(goal.type) filtered to equalities
  │   other       → no retrieval (family-only suggestion)
  │
  │ → [(full_tactic, score), ...]
  ▼
suggest_tactics MCP tool response
  │
  │ Merge: argument-enriched suggestions first, then family-only, then rule-based
  ▼
list[TacticSuggestion]
```

### ArgumentRetriever

The `ArgumentRetriever` class maps tactic families to retrieval strategies:

```
class ArgumentRetriever:
    pipeline_context: PipelineContext | None   # search index (may be absent)

    retrieve(family, goal, hypotheses, limit=5) → list[(tactic_text, score)]
```

**Retrieval strategies by family:**

| Family | Strategy | Rationale |
|--------|----------|-----------|
| `apply` | `search_by_type(goal.type, limit)` | Lemmas whose conclusion matches the goal type can be applied directly |
| `exact` | `search_by_type(goal.type, limit)` | Same as `apply` but the match must be exact (no unification residuals) |
| `rewrite` | `search_by_type(goal.type, limit)` filtered to equalities | Rewrite requires an equality lemma; filter results for `=` in the statement |
| Others | No retrieval | Families like `intros`, `simpl`, `auto`, `destruct`, `induction` either take no arguments, take hypothesis names (already in context), or take non-lemma arguments |

**Hypothesis-based candidates:** For `apply` and `rewrite`, hypotheses in the proof context are also candidates. Hypotheses whose type matches the goal (for `apply`) or contains an equality (for `rewrite`) are included alongside retrieval results, with a fixed high score.

**Graceful degradation:** When `pipeline_context` is None (no search index loaded), the retriever returns an empty list and the system falls back to family-only suggestions.

### Integration with suggest_tactics

The argument retriever is called after neural prediction but before response construction:

1. Neural predictor returns top-K families with confidence scores
2. For each family with confidence >= threshold:
   a. If the family takes lemma arguments, call `ArgumentRetriever.retrieve()`
   b. For each candidate, construct a full tactic suggestion: `"{family} {candidate.name}"`
   c. Score = family_confidence × candidate_retrieval_score
3. Merge argument-enriched suggestions with family-only suggestions and rule-based suggestions
4. Deduplicate and apply limit

### Candidate Scoring

Each argument candidate's final score combines two signals:

```
score = family_confidence × retrieval_score
```

where `family_confidence` is the neural classifier's softmax probability and `retrieval_score` is the retrieval pipeline's [0, 1] relevance score. This naturally ranks suggestions where both the tactic family and the argument are confident highest.

---

## Differences from Previous Neural Retrieval Design

The previous design (documented in `doc/neural-network-search.md`) used a bi-encoder to produce 768-dim embeddings for cosine similarity search over a FAISS index. That approach was abandoned because only ~3,500 training pairs could be extracted (insufficient for competitive retrieval quality).

The tactic prediction design differs in every dimension:

| Aspect | Previous (retrieval) | Current (tactic prediction) |
|--------|---------------------|----------------------------|
| Task | Premise retrieval (ranking) | Tactic family classification |
| Training data | ~3,500 (state, premises) pairs | ~105,000 (state, tactic) pairs |
| Model output | 768-dim embedding | Class logits (~30 classes) |
| Inference | Encode + FAISS search | Single forward pass + softmax |
| Index integration | Embeddings stored in index.db | No index integration |
| Search involvement | RRF fusion with other channels | None — standalone tool |
