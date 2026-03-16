# Before You Start

Read `index.md` to understand what documents exist in this directory and their purposes.

## Research Documents

**Layer:** Reference — supports all layers

**Location:** `doc/background/<topic>.md`

**Authority:** Research documents are **reference material** — they inform but do not constrain any other layer. They have no downstream authority. No other document is derived from research documents; instead, they provide evidence that supports or challenges design decisions made in feature and architecture documents.

**When writing or editing research documents:**

- Capture background research: technology surveys, current art, academic literature reviews, benchmarks.
- Include factual findings with source citations, comparative analysis of approaches, and evidence supporting or challenging design decisions.
- Do **not** discuss or mention the product described in the parent folder. These files review the state of the art only.
- Do **not** include requirements or specification statements — research documents are reference material.
- These are not consumed by the LLM spec-extraction pipeline.

**One per:** research topic or investigation
