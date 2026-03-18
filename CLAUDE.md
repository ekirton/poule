# Directory structure

Each layer answers "what" for the layer below and "how" for the layer above. A specification at any level describes the "what" for the next level down — customer needs define "what," system decomposition defines "how," and that decomposition becomes the "what" for component-level specs.

## Layer 1 : Stakeholder intent

* doc/requirements/ : business goals, user needs, immutable constraints

## Layer 2 : Behavioral specification

* doc/requirements/stories/ : user stories with acceptance criteria
* doc/features/ : what and why, design rationale

## Layer 3 : Design specification

* doc/architecture/ : how, at design level
* specification/ : derived from architecture, authorative for implementation

## Layer 4 : Implementation specification

* tasks/ : detailed plan for implementation

## Layer 5 : Implementation

* src/
* test/
* commands/ : slash command prompt files (agentic workflows)

# Pull Request Process

Do not push to a remote branch after every commit. Push only when the branch is ready to merge — the user makes many commits before a branch is ready. When ready:

1. Review the commit log and set a descriptive PR title: `git log --oneline origin/main..HEAD`, then `gh pr edit <number> --title "..."` — the PR title becomes the squash commit message on `main`.
2. Push the branch and open a PR: `git push origin <branch> && gh pr create`
3. Enable auto-merge so it merges once CI passes: `gh pr merge <number> --auto --squash`

If the branch is out of date with `main`, rebase before pushing: `git rebase origin/main`.

# Diagram Visualization

When a user asks to visualize proofs, dependencies, or proof states, use the `visualize_*` MCP tools (`visualize_proof_state`, `visualize_proof_tree`, `visualize_dependencies`, `visualize_proof_sequence`). These tools write a `proof-diagram.html` file to the project directory as a side effect. After calling a visualization tool, tell the user to open `proof-diagram.html` in their browser.

Do not use external Mermaid rendering services (mermaid.ai, mermaid.ink, Mermaid Chart MCP). All diagram rendering is local via the HTML file.
