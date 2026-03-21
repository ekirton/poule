# Few-Shot Context Retrieval

Retrieval of similar proof states and their successful tactics from extracted training data, used as few-shot context to improve tactic candidate generation during proof search.

---

## Problem

When proof search generates tactic candidates via an LLM, the LLM works from the current proof state and retrieved premises. It has no direct knowledge of what tactics have historically succeeded on similar proof states in existing Coq developments. A proof state involving `nat` induction in a MathComp context, for example, might benefit from seeing that similar goals were solved by `elim/case` patterns in MathComp's ssreflect style — but the LLM has no way to discover this at search time.

## Solution

When extracted training data (Phase 3) is available for the libraries in scope, the proof search tool retrieves similar proof states and their successful tactic sequences from the extracted dataset. These (state, tactic) pairs are included as few-shot examples in the LLM prompt for candidate generation.

The retrieval is similarity-based: given the current proof state (goal type, hypothesis types, symbols present), find the most similar proof states in the training data by structural and symbolic overlap. The matched states' successful tactics serve as concrete examples of what has worked before in comparable situations.

## Availability

Few-shot context retrieval is optional. It activates when:

- Extracted training data exists for at least one library in the current project's dependency chain
- The training data includes per-step proof state and tactic information (the standard extraction format from Phase 3)

When no training data is available, proof search operates without few-shot augmentation — using only the proof state, local context, and retrieved premises from Semantic Lemma Search. The search is fully functional without training data; few-shot context improves candidate quality but is not required.

## Design Rationale

### Why few-shot context rather than fine-tuning

Fine-tuning a model on extracted Coq proof data would produce better tactic predictions. But fine-tuning requires training infrastructure, GPU compute, and model management — all out of scope for this initiative. Few-shot prompting achieves a meaningful fraction of the benefit (the LLM sees concrete examples of successful tactics in context) without any infrastructure beyond the extracted data and a similarity query.

### Why retrieve from training data rather than from the current file

The current file's completed proofs are a useful signal (the developer's style, the local proof patterns), but they represent a tiny sample. Training data from stdlib, MathComp, and other projects provides thousands of (state, tactic) pairs covering a wide range of proof patterns. The two sources are complementary — in-file proofs capture local style, training data captures global patterns.

### Why this is not a standalone tool

Few-shot retrieval is consumed internally by proof search during candidate generation. There is no user-facing scenario where someone wants to retrieve few-shot examples without immediately using them for tactic generation. Exposing it as a separate MCP tool would add to the tool count without a distinct use case. If a future need arises (e.g., Claude wants to show the user similar proofs for educational purposes), it can be extracted into its own tool at that time.
