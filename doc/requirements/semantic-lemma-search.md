# Semantic Lemma Search for Coq/Rocq — Product Requirements Document

Cross-reference: see [coq-ecosystem-opportunities.md](coq-ecosystem-opportunities.md) for ecosystem context and initiative sequencing.
Cross-reference: see [modular-index-distribution.md](modular-index-distribution.md) for per-library index distribution.

## 1. Business Goals

Coq/Rocq users consistently cite lemma discoverability as their top daily friction. The built-in `Search` command is purely syntactic — users must already know the approximate shape of what they seek. Lean has at least six actively maintained search tools; Coq has none.

This initiative delivers a semantic lemma search engine for Coq/Rocq libraries, exposed as an MCP server for Claude Code. It provides immediate, standalone value to every Coq user with access to Claude Code and establishes the retrieval infrastructure required by future AI-for-Coq tools (copilot, neural premise selection).

**Success metrics:**
- ≥ 70% recall@50 on a hand-curated evaluation set of common Coq search tasks
- < 1 second end-to-end retrieval latency for indexes up to 50K declarations
- Successful indexing of any configured Coq library set without GPU, API keys, or network access

---

## 2. Target Users

| Segment | Needs | Priority |
|---------|-------|----------|
| Coq developers using Claude Code | Find lemmas by name, type, structure, or natural language description within a conversational workflow | Primary |
| Users of supported libraries | Search across configured libraries (e.g., MathComp, stdpp, Flocq) alongside stdlib | Primary |
| Coq developers working on custom projects | Index and search their own declarations alongside library declarations | Secondary |

---

## 3. Competitive Context

Cross-references:
- [Neural retrieval architectures survey](../background/neural-retrieval-architectures-2025-2026.md)
- [Semantic search state-of-the-art](../background/semantic-search.md)
- [Tree-based retrieval background](../background/tree-based-retrieval.md)

**Lean ecosystem (comparative baseline):**
- Loogle: formal pattern search over type signatures
- Moogle: natural language search via embeddings
- Lean Finder: 81.6% user upvote rate by aligning search with user intent
- LeanSearch: NL search integrated with Lean tooling
- LeanHammer: neural premise selection achieving 72.7% R@32

**Coq ecosystem (current state):**
- Built-in `Search`: syntactic only, no ranking, no fuzzy matching
- No natural language search
- No embedding-based retrieval
- No type-directed search with semantic ranking

**Key research findings informing design:**
- Neural+symbolic union outperforms either alone by 21% (LeanHammer)
- Graph structure adds +26% R@10 (dependency graph exploitation)
- Training-free tree-based methods are competitive with neural approaches for structural retrieval
- Domain-specific tokenization significantly improves formal-language embeddings
- The retrieval bottleneck: making existing lemmas discoverable is more impactful than generating new ones (LEGO-Prover)

---

## 4. Requirement Pool

### P0 — Must Have

| ID | Requirement |
|----|-------------|
| R-P0-1 | Index all declarations from the Coq standard library with a single CLI command |
| R-P0-2 | Index any combination of supported libraries in the same database (see [modular-index-distribution](modular-index-distribution.md) for library selection) |
| R-P0-3 | Store the index in a single SQLite database with no external service dependencies |
| R-P0-4 | Expose search tools via an MCP server compatible with Claude Code (stdio transport) |
| R-P0-5 | Support search by name pattern (glob/regex on fully qualified names) |
| R-P0-6 | Support search by type expression, using multiple retrieval channels |
| R-P0-7 | Support search by structural similarity to a given expression |
| R-P0-8 | Support search by symbol set (constants, inductives, constructors) |
| R-P0-22 | Indexed symbol sets must contain fully qualified kernel names, not short or display names |
| R-P0-23 | Symbol search must accept short names, partial qualifications, or fully qualified names and resolve them to FQNs before matching |
| R-P0-24 | Type search must normalize user queries to bridge the representation gap between how users write type patterns (free variables, short names, no quantifiers) and how types are stored in the index (bound variables, FQNs, fully quantified) |
| R-P0-9 | Retrieve full declaration details including dependencies and dependents |
| R-P0-10 | Navigate the dependency graph from a known declaration |
| R-P0-11 | List modules under a given prefix |
| R-P0-12 | Fuse results across retrieval channels so items appearing in multiple channels rank higher |
| R-P0-13 | Achieve ≥ 70% recall@50 on a hand-curated evaluation set |
| R-P0-14 | Complete first-pass retrieval in < 1 second for indexes up to 50K declarations |
| R-P0-15 | Indexing must not require a GPU, external API keys, or network access |
| R-P0-16 | Record the index schema version in the database; reject incompatible indexes at startup |
| R-P0-17 | When the indexed library is updated, rebuild the index immediately before serving queries |
| R-P0-18 | When the indexing command is run and an existing database file exists at the output path, delete it and rebuild from scratch without prompting |
| R-P0-19 | Expose all search capabilities (name, type, structure, symbol, lemma detail, related declarations, module listing) as standalone CLI commands |
| R-P0-20 | CLI search commands shall output results to stdout in both human-readable and machine-readable (JSON) formats |
| R-P0-21 | CLI search commands shall reuse the same retrieval pipeline as the MCP server with identical ranking behavior |

### P1 — Should Have

| ID | Requirement |
|----|-------------|
| R-P1-1 | Index a user project directory alongside library declarations |
| R-P1-2 | Incremental re-indexing: update changed declarations without full rebuild |
| R-P1-3 | Normalize Coq expressions before indexing to eliminate surface-level syntactic variation |
| R-P1-4 | Natural language lemma search via LLM-mediated query formulation over MCP tools |
| R-P1-5 | Iterative refinement: LLM automatically reformulates queries when initial results are insufficient |

### P2 — Nice to Have

| ID | Requirement |
|----|-------------|
| R-P2-1 | Graceful degradation when individual declarations fail to extract during indexing |

---

## 5. Scope Boundaries

**In scope:**
- Semantic lemma search for Coq/Rocq libraries
- MCP server deployment for Claude Code integration (stdio transport)
- Standalone CLI search tool (same retrieval capabilities as MCP, for terminal workflows)
- Offline indexing CLI for configured libraries and user projects
- Tree-based and symbolic retrieval channels (no neural embeddings in v1)
- SQLite-based local index storage

**Out of scope (this initiative):**
- Web interface deployment
- coq-lsp / IDE plugin deployment
- Neural embedding models or GPU-dependent retrieval
