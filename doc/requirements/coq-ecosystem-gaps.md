# Coq/Rocq Ecosystem — Opportunity Landscape

## 1. Ecosystem Overview

The Coq/Rocq ecosystem has several unmet needs that hinder adoption and productivity. The Lean ecosystem has surged ahead with purpose-built tooling for search, proof interaction, and AI integration. Coq's tooling gaps span discoverability, proof interaction, training data extraction, and developer experience. This document captures the full opportunity set; per-initiative PRDs contain detailed requirements.

---

## 2. Opportunity Table

| Opportunity | Gap Severity | Dependencies | Primary Beneficiary | Initiative PRD |
|-------------|-------------|-------------|---------------------|----------------|
| Semantic Lemma Search | High | None | All Coq users | [semantic-lemma-search.md](semantic-lemma-search.md) |
| Proof Interaction Protocol | Medium-High | None | Tool builders, AI researchers | [proof-interaction-protocol.md](proof-interaction-protocol.md) |
| Training Data Extraction | High | Interaction Protocol | AI researchers, tool builders | [training-data-extraction.md](training-data-extraction.md) |
| Proof Search & Automation | High | Interaction Protocol, Search | All Coq users | [proof-search-automation.md](proof-search-automation.md) |
| Neural Premise Selection | Medium | Extraction | CoqHammer users, researchers | [neural-premise-selection.md](neural-premise-selection.md) |
| Proof Visualization Widgets | High | None | Educators, formalization developers | [proof-visualization-widgets.md](proof-visualization-widgets.md) |
| CI/CD Tooling | Medium | None | All Coq project maintainers | — (out of scope) |
| Package Registry | Medium | None (benefits from CI/CD) | All Coq users, especially newcomers | — (out of scope) |
