# Coq/Rocq Ecosystem — Opportunity Landscape

## 1. Ecosystem Overview

The Coq/Rocq ecosystem has several unmet needs that hinder adoption and productivity. The Lean ecosystem has surged ahead with purpose-built tooling for search, proof interaction, and AI integration. Coq's tooling gaps span discoverability, proof interaction, training data extraction, and developer experience. This document captures the full opportunity set and initiative sequencing; per-initiative PRDs contain detailed requirements.

---

## 2. Opportunity Table

| Opportunity | Gap Severity | Dependencies | Primary Beneficiary | Initiative PRD |
|-------------|-------------|-------------|---------------------|----------------|
| Semantic Lemma Search | High | None | All Coq users | [semantic-lemma-search.md](semantic-lemma-search.md) |
| Proof Interaction Protocol | Medium-High | None | Tool builders, AI researchers | [proof-interaction-protocol.md](proof-interaction-protocol.md) |
| Training Data Extraction | High | Interaction Protocol | AI researchers, tool builders | [training-data-extraction.md](training-data-extraction.md) |
| LLM Copilot | High | Extraction, Search | All Coq users | [llm-copilot.md](llm-copilot.md) |
| Neural Premise Selection | Medium | Extraction | CoqHammer users, researchers | — |
| Proof Visualization Widgets | High | None | Educators, formalization developers | [proof-visualization-widgets.md](proof-visualization-widgets.md) |
| CI/CD Tooling | Medium | None | All Coq project maintainers | — |
| Package Registry | Medium | None (benefits from CI/CD) | All Coq users, especially newcomers | — |

---

## 3. Initiative Sequencing

```
Phase 1 (Complete):
  Semantic Lemma Search          -- no dependencies; solves daily pain

Phase 2 (Active):
  Proof Interaction Protocol     -- standalone value; enables Phases 3 and 4
  Proof Visualization Widgets    -- independent; MCP + Mermaid approach

Phase 3 (AI Infrastructure):
  Training Data Extraction       -- depends on Interaction Protocol

Phase 4 (AI Applications):
  LLM Copilot                   -- depends on Extraction and Semantic Search
  Neural Premise Selection       -- depends on Extraction

Phase 5 (Ecosystem Polish):
  CI/CD Tooling                  -- independent; enables Package Registry
  Package Registry               -- benefits from CI/CD Tooling
```
