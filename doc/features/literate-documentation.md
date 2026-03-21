# Literate Documentation

Coq proof scripts become self-contained, interactive documents that any reader can explore in a browser — no IDE, no local Coq installation required. Claude generates these documents on demand from `.v` files by invoking Alectryon, turning opaque tactic sequences into browsable pages where every proof step reveals its resulting proof state on hover or click.

---

## Problem

Proof scripts are opaque without an interactive IDE. A `.v` file opened in a text editor or code review tool shows tactic invocations but not the proof states they produce — the reader must mentally replay each step or open the file in CoqIDE or Proof General to understand what is happening. This makes proof scripts difficult to teach from, difficult to review, and difficult to publish as explanatory material.

Sharing proof understanding today requires copy-pasting fragments from an IDE into a document, losing interactivity and context in the process. An educator preparing lecture materials must screenshot proof states. A reviewer must install Coq tooling and replay the proof locally. A library author publishing documentation settles for coqdoc output that shows definitions and comments but never the proof states that make a proof comprehensible.

## Solution

### Single-File Generation

Given a `.v` file, Claude produces a complete interactive HTML page where every Coq sentence is paired with the proof state it produces. The output is self-contained — all styles and scripts are embedded — so the file can be opened directly in any modern browser with no additional setup. The user can specify where the HTML file is written, placing it directly into a project's documentation directory for publication.

### Proof-Scoped Generation

When the user is interested in a single proof rather than an entire file, Claude generates documentation scoped to a named theorem, lemma, or definition and its immediately surrounding context. Every tactic step within the proof shows its resulting proof state. This lets a reviewer focus on the proof under discussion without wading through an entire development, and lets an educator extract a single proof as a teaching artifact.

### Batch Generation

For project-wide documentation, Claude processes all `.v` files in a directory tree, preserving the project's directory structure in the output. The result includes cross-file navigation links so readers can browse between modules, and an index page that serves as the entry point for the entire documentation set. If individual files fail to compile, documentation is still generated for the files that succeed — failures are reported without aborting the batch.

### Output Customization

The generated documentation can take several forms depending on the user's needs: a standalone HTML page for direct viewing, an HTML fragment suitable for embedding into an existing website or slide deck, or LaTeX output for printed materials. Users with specific formatting preferences can pass custom Alectryon flags to control behavior such as line wrapping thresholds and caching.

## Design Rationale

### Why Alectryon

Alectryon is the mature, actively maintained tool for this job. It captures Coq's output sentence by sentence and produces interactive HTML with inline proof state display. It supports both reStructuredText and Markdown literate styles and is already used by major teaching materials including Software Foundations. Wrapping an established tool avoids reinventing proof state capture and HTML generation, and ensures the output is compatible with what the Coq community already uses and expects.

### Why this complements Poule's other tools

Literate documentation generation is a natural endpoint for workflows that begin with other Poule tools. After proof search finds a proof, the user can immediately generate browsable documentation for it. After semantic lemma search identifies relevant results, the user can produce a documented overview of how those lemmas are used in a development. Documentation generation turns Poule's interactive proof capabilities into shareable artifacts — the proof understanding that Claude helps build during a session can be captured and published rather than lost when the conversation ends.

### Graceful handling when Alectryon is not installed

Alectryon is not bundled with Poule — it is a Python package that users install separately. When Alectryon is not found on the system, the tool reports a clear error with installation instructions rather than failing with a cryptic message. When an outdated version is detected, the tool identifies the installed version and the minimum required version. This keeps the dependency boundary clean: Poule wraps Alectryon but does not own it, and users are guided toward resolving any installation issues themselves.

---

## Acceptance Criteria

### Generate Interactive Documentation for a Coq Source File

**Priority:** P0
**Stability:** Stable

- GIVEN a `.v` file that compiles without errors WHEN the documentation generation MCP tool is called with the file path THEN it returns self-contained HTML with interactive proof state display for every Coq sentence
- GIVEN the generated HTML file WHEN it is opened in a modern browser with no additional setup THEN all proof states are accessible via hover or click interactions and all CSS/JavaScript is embedded
- GIVEN a `.v` file containing 3 theorem proofs and 5 definitions WHEN documentation is generated THEN all 3 proofs show inline proof states and all 5 definitions are included in the output

**Traces to:** R-LD-P0-1, R-LD-P0-2, R-LD-P0-6

### Write Documentation Output to a Specified Path

**Priority:** P0
**Stability:** Stable

- GIVEN a `.v` file and an output path WHEN the documentation tool is called with both parameters THEN the HTML file is written to the specified output path
- GIVEN an output path whose parent directory does not exist WHEN the tool is called THEN it returns an error indicating the directory does not exist, rather than silently failing

**Traces to:** R-LD-P0-6

### Generate Documentation for a Specific Proof

**Priority:** P0
**Stability:** Stable

- GIVEN a `.v` file containing proofs for `lemma_A`, `theorem_B`, and `lemma_C` WHEN the proof-scoped documentation tool is called with the file path and the name `theorem_B` THEN the output contains interactive documentation for `theorem_B` and its immediately surrounding context (e.g., the statement and any local definitions it depends on)
- GIVEN a `.v` file and a proof name that does not exist in the file WHEN the tool is called THEN it returns an error listing the available proof names in the file
- GIVEN a proof that uses `Proof. ... Qed.` spanning 15 tactic steps WHEN proof-scoped documentation is generated THEN every tactic step shows its resulting proof state

**Traces to:** R-LD-P0-3

### Generate Documentation for an Entire Project

**Priority:** P1
**Stability:** Stable

- GIVEN a project directory containing 10 `.v` files across 3 subdirectories WHEN the batch documentation tool is called with the project root THEN HTML documentation is generated for all 10 files, preserving the directory structure in the output
- GIVEN batch-generated documentation WHEN a user opens any generated page THEN navigation links to other documented files in the project are present and functional
- GIVEN a batch run where 9 of 10 files compile successfully and 1 file has a compilation error THEN documentation is generated for the 9 successful files and the error for the failing file is reported without aborting the entire batch

**Traces to:** R-LD-P1-1, R-LD-P1-4

### Generate an Index Page for Batch Output

**Priority:** P1
**Stability:** Stable

- GIVEN batch documentation generated for 10 files WHEN the index page is opened in a browser THEN it lists all 10 documented files with working links to each
- GIVEN that 1 of 10 files failed during batch generation WHEN the index page is rendered THEN the failing file is listed with a note indicating documentation was not generated, and the 9 successful files link correctly

**Traces to:** R-LD-P1-1, R-LD-P1-4

### Select Output Format

**Priority:** P1
**Stability:** Draft

- GIVEN a `.v` file WHEN the documentation tool is called with format set to "html" THEN the output is a complete standalone HTML page with embedded styles and scripts
- GIVEN a `.v` file WHEN the documentation tool is called with format set to "html-fragment" THEN the output is an HTML fragment without `<html>`, `<head>`, or `<body>` wrapper tags, suitable for embedding in an existing page
- GIVEN a `.v` file WHEN the documentation tool is called with format set to "latex" THEN the output is a LaTeX document using Alectryon's LaTeX backend

**Traces to:** R-LD-P1-2

### Pass Custom Alectryon Flags

**Priority:** P1
**Stability:** Draft

- GIVEN the flag `--long-line-threshold 80` passed to the documentation tool WHEN documentation is generated THEN Alectryon applies the 80-character line wrapping threshold to the output
- GIVEN the flag `--cache-directory /tmp/alectryon-cache` passed to the tool WHEN documentation is generated THEN Alectryon uses the specified cache directory for compilation artifacts

**Traces to:** R-LD-P1-3

### Report Missing Alectryon Installation

**Priority:** P0
**Stability:** Stable

- GIVEN that Alectryon is not installed or not on the system PATH WHEN any documentation generation MCP tool is called THEN it returns an error message stating that Alectryon was not found, along with installation instructions (e.g., `pip install alectryon`)
- GIVEN that Alectryon is installed but the version is older than the minimum supported version WHEN the tool is called THEN it returns a warning identifying the installed version and the minimum required version

**Traces to:** R-LD-P0-5

### Report Coq Compilation Errors

**Priority:** P0
**Stability:** Stable

- GIVEN a `.v` file with a type error on line 42 WHEN the documentation tool is called THEN it returns an error that includes the line number (42), the Coq error message, and the fragment of source code where the error occurs
- GIVEN a `.v` file that requires a library not in the current load path WHEN the documentation tool is called THEN the error message includes Coq's "Cannot find a physical path" message and the name of the missing dependency

**Traces to:** R-LD-P0-4
