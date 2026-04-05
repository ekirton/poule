# Background Research Index

Surveys and analyses of the state of the art. Documents here describe what exists today — they do not discuss or propose the product described in the parent directory.

---

## Coq/Rocq Ecosystem

| File | Summary |
|------|---------|
| [coq-ai-theorem-proving.md](coq-ai-theorem-proving.md) | Survey of AI-assisted theorem proving tools for Coq/Rocq; covers training data infrastructure, the broader AI proving landscape, and the growing gap between Coq and Lean in AI tooling. |
| [coq-tactics.md](coq-tactics.md) | Reference for Coq tactic families observed in the tactic prediction training corpus; definitions grouped by role (introduction, elimination, rewriting, automation, SSReflect, arithmetic, proof structuring). |
| [coq-ecosystem-tooling.md](coq-ecosystem-tooling.md) | State of the art in Coq/Rocq tooling: IDE support, documentation, package management, CI/CD, proof visualization, and comparison with the Lean 4 ecosystem. |
| [coq-library-ecosystem.md](coq-library-ecosystem.md) | Survey of the Coq/Rocq library ecosystem: standard libraries, mathematics, verification, meta-programming, automation, and community infrastructure; includes size, maintenance status, proof style, and cross-cutting ecosystem observations. |
| [coq-premise-retrieval.md](coq-premise-retrieval.md) | Premise selection and lemma retrieval for Coq/Rocq: what exists today, state of the art in Lean and Isabelle, and research findings that inform future tool development. |
| [common-questions.md](common-questions.md) | Taxonomy of recurring questions in Coq/Rocq and Lean communities, drawn from Discourse, Zulip, Stack Overflow, GitHub issues, Reddit, and mailing lists; clustered by kind with concrete examples. |

---

## Neural Retrieval Methods

| File | Summary |
|------|---------|
| [neural-retrieval.md](neural-retrieval.md) | Survey of neural architectures for premise selection and semantic search over formal math libraries; covers architecture families, training methods, compute, and deployment. |
| [neural-retrieval-architectures-2025-2026.md](neural-retrieval-architectures-2025-2026.md) | Deep-dive on neural retrieval architectures for formal math and code semantic search as of 2025–2026. |
| [neural-encoder-architectures-premise-selection.md](neural-encoder-architectures-premise-selection.md) | Architectures, training strategies, and performance benchmarks for neural encoders used in premise selection across Coq, Lean, and Isabelle. |
| [compute-requirements-neural-retrieval-formal-math.md](compute-requirements-neural-retrieval-formal-math.md) | Training compute, inference cost, scaling laws, and deployment requirements for neural retrieval models in formal mathematics and code search. |

---

## Tree-Based and Structural Retrieval

| File | Summary |
|------|---------|
| [tree-based-retrieval.md](tree-based-retrieval.md) | Survey of training-free, structure-aware retrieval methods for formal math libraries; includes implementation-level detail for a Coq/Rocq retrieval system. |
| [tree-based-structural-premise-selection.md](tree-based-structural-premise-selection.md) | Deep research on tree-based and structural methods for premise selection; implementation-focused companion to the above survey. |

---

## Training Methods

| File | Summary |
|------|---------|
| [class-imbalance.md](class-imbalance.md) | Class imbalance techniques for neural network training: loss re-weighting, decoupled training, data-level methods, and the finding that standard pipeline tuning can match specialized approaches. |

---

## Semantic Search, Vector Databases, and MCP

| File | Summary |
|------|---------|
| [semantic-search.md](semantic-search.md) | Semantic search architectures, retrieval methods, and delivery mechanisms for Coq/Rocq formal libraries; covers Lean ecosystem deployed tools and LLM-augmented retrieval patterns. |
| [vector-db-rag-formal-math-research.md](vector-db-rag-formal-math-research.md) | State of the art in vector databases and embedding-based RAG for semantic search over formal mathematical libraries. |
| [mcp-search-retrieval-survey.md](mcp-search-retrieval-survey.md) | Survey of exposing search/retrieval services via the Model Context Protocol (MCP) for LLM reasoning workflows. |
