You are executing the `/textbook` command. Your job is to retrieve and present relevant passages from the Software Foundations textbook in response to the user's query about a Coq concept, tactic, or proof technique.

The user provides a query in one of these forms:

- A natural-language question (e.g., "how does induction work?")
- A tactic or concept name (e.g., "rewrite", "propositions")
- A query with a volume filter (e.g., `--volume lf what is a proposition`)

## Step 1: Parse the input

Extract the query text from the user's message. If the user specified `--volume <abbrev>`, extract the volume abbreviation and pass it as a filter. Valid volume abbreviations: `lf` (Logical Foundations), `plf` (Programming Language Foundations), `vfa` (Verified Functional Algorithms), `qc` (QuickChick), `secf` (Security Foundations), `slf` (Separation Logic Foundations), `vc` (Verifiable C).

If no query is provided, ask the user what Coq concept or tactic they want to look up.

## Step 2: Retrieve passages

Call `education_context` with:
- `query`: the user's query text
- `limit`: 5 (default)
- `volume`: the volume abbreviation if specified, omit otherwise

If the tool returns an error with code `EDUCATION_UNAVAILABLE`, tell the user: "The Software Foundations textbook database is not available in this environment. The education database must be built and included in the Docker container."

If the tool returns no results, tell the user: "No matching passages found in Software Foundations. Try rephrasing your query or using a different term."

## Step 3: Present results

For each returned passage, format the output as:

1. **Source citation** in bold: "**Software Foundations, {location}**"
2. The passage text, with any Coq code blocks formatted as ```coq code fences
3. A browser link: "Open in browser: `{browser_path}`"

Separate passages with a horizontal rule (`---`).

After all passages, add a note: "Open any of the paths above in your browser to read the full chapter."

## Edge cases

- **Very long passages:** If a passage exceeds 50 lines, show the first 30 lines and tell the user the passage continues in the full chapter.
- **Multiple relevant volumes:** If results span multiple volumes, group them by volume with a volume header.
- **Query is a Coq expression:** If the query looks like Coq code (contains `:`, `forall`, `->`, etc.), search for it as-is — the semantic search handles mixed natural language and formal syntax.
