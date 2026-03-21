# Directory structure

Each layer answers "what" for the layer below and "how" for the layer above. A specification at any level describes the "what" for the next level down — customer needs define "what," system decomposition defines "how," and that decomposition becomes the "what" for component-level specs.

## Layer 1 : Stakeholder intent

* doc/requirements/ : business goals, user needs, immutable constraints

## Layer 2 : Behavioral specification

* doc/features/ : what and why, design rationale, acceptance criteria

## Layer 3 : Design specification

* doc/architecture/ : how, at design level
* specification/ : derived from architecture, authorative for implementation

## Layer 4 : Implementation specification

* tasks/ : detailed plan for implementation

## Layer 5 : Implementation

* src/
* test/
* commands/ : slash command prompt files (agentic workflows)

# SDD Layer Enforcement

Use `/diagnose` to investigate a bug and determine which SDD layer to fix first. Use `/sdd <layer> "description"` to execute a fix from that layer downward. Use `/requirements`, `/features`, `/architecture`, `/specification`, `/tasks`, `/tests`, or `/implementation` to enter a single phase. Use `/free` to disable enforcement.

# Pull Request Process

Do not push to a remote branch after every commit. Push only when the branch is ready to merge — the user makes many commits before a branch is ready.

**Never create a PR or enable auto-merge without explicit user approval.** CI runs automatically on push and auto-merge is configured on PRs, so an unauthorized PR can merge to main before the user reviews it. Always ask the user before creating a PR.

When the user says the branch is ready:

1. Review the commit log and set a descriptive PR title: `git log --oneline origin/main..HEAD`, then `gh pr edit <number> --title "..."` — the PR title becomes the squash commit message on `main`.
2. Push the branch and open a PR: `git push origin <branch> && gh pr create`
3. Enable auto-merge so it merges once CI passes: `gh pr merge <number> --auto --squash`

If the branch is out of date with `main`, rebase before pushing: `git rebase origin/main`.

Always create new branches from an up-to-date `main`: `git checkout main && git pull origin main && git checkout -b <new-branch>`. Never branch from a feature branch — this causes "out of date with base branch" errors on GitHub when the parent branch merges first.

# Diagram Visualization

When a user asks to visualize proofs, dependencies, or proof states, use the `visualize_*` MCP tools (`visualize_proof_state`, `visualize_proof_tree`, `visualize_dependencies`, `visualize_proof_sequence`). These tools write a `proof-diagram.html` file to the project directory as a side effect. After calling a visualization tool, tell the user to open `proof-diagram.html` in their browser.

Do not use external Mermaid rendering services (mermaid.ai, mermaid.ink, Mermaid Chart MCP). All diagram rendering is local via the HTML file.
