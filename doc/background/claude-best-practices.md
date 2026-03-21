# Claude Code Best Practices

A comprehensive guide to getting the most out of Claude Code — covering guidance files, skills, agents, hooks, channels, MCP servers, control loops, context management, headless mode, and more.

---

## 1. Guidance Files (CLAUDE.md)

### Authoring Principles

**Imperative over descriptive.** Write imperative instructions rather than descriptive ones — "Use TypeScript strict for all new files" not "The project uses TypeScript". Claude treats imperatives as rules and descriptions as optional context. A CLAUDE.md with 15 imperative rules produces compliant code in 94% of cases; the same content written descriptively drops to 73%.

**Keep it short and surgical.** For each line, ask: "Would removing this cause Claude to make mistakes?" If not, cut it. Bloated CLAUDE.md files cause Claude to ignore your actual instructions. If Claude keeps doing something you don't want despite having a rule against it, the file is probably too long and the rule is getting lost.

**Hard size limit.** Cap your CLAUDE.md at 200 lines. Beyond that, late instructions risk being truncated during context compression.

**Emphasis for critical rules.** Add emphasis (e.g., "IMPORTANT" or "YOU MUST") to improve adherence. For domain-specific rules in longer files, wrapping them in `<important if="...">` tags helps prevent Claude from ignoring them as files grow longer.

**Concrete and verifiable.** Write instructions that are concrete enough to verify. "Use 2-space indentation" not "Format code properly"; "Run npm test before committing" not "Test your changes"; "API handlers live in src/api/handlers/" not "Keep files organized".

**Negative rules are equally powerful.** Negative rules are as powerful as positive ones — list explicitly what Claude must not do.

**Use `@`-imports to stay modular.** CLAUDE.md files can import additional files using `@path/to/import` syntax. This lets you compose instructions without bloating the main file. Recursive imports are supported up to 5 hops.

**Keep it current.** Treat CLAUDE.md like code: review it when things go wrong, prune it regularly, and test changes by observing whether Claude's behavior actually shifts. If two rules contradict each other, Claude may pick one arbitrarily.

### The CLAUDE.md Hierarchy

Place instructions at the right scope:

| Location | Scope | Shared? |
|----------|-------|---------|
| Managed policy (`/Library/Application Support/ClaudeCode/CLAUDE.md`) | Organization | IT-controlled |
| `./CLAUDE.md` or `./.claude/CLAUDE.md` | Project | Yes (git) |
| `~/.claude/CLAUDE.md` | User (all projects) | No |
| `.claude/rules/*.md` (with glob frontmatter) | Path-specific | Yes (git) |

Place team conventions in the project root, personal preferences in user-level, and file-type or path-specific rules in `.claude/rules/*.md` with glob patterns.

### Path-Specific Rules

Scope rules to matching files so they load on-demand instead of always:

```markdown
---
paths:
  - "src/api/**/*.ts"
  - "tests/**/*.test.ts"
---

# API Rules
- All endpoints require input validation
- Use consistent error response format
```

This keeps your root CLAUDE.md lean while still providing context-specific guidance.

---

## 2. Skills

### What Skills Are

Skills are markdown files that extend Claude's capabilities with custom instructions and workflows. They combine YAML frontmatter (configuration) and markdown body (instructions). They load on demand — unlike CLAUDE.md, which loads every session.

### Authoring Principles

**Conciseness is critical.** Only add context Claude doesn't already have. The context window is shared with everything else — conversation history, other skills, and your request.

**Match specificity to fragility.** Use high freedom (natural language steps) when multiple approaches are valid. Use medium freedom (pseudocode with parameters) when a preferred pattern exists. Use low freedom (exact scripts) when operations are fragile or a specific sequence must be followed. Narrow bridge with cliffs → exact instructions. Open field → general direction.

**Front matter drives discovery.** The `description` field is critical — Claude uses it to choose the right skill from potentially 100+ available. Write in third person, include both what the skill does and specific triggers for when to use it.

**Use gerund naming.** Use verb + -ing form for skill names (e.g., `deploying`, `reviewing-code`). The `name` field must use only lowercase letters, numbers, and hyphens.

**Build a "Gotchas" section.** Highest-signal content; add Claude's failure points over time.

**Progressive disclosure with subdirectories.** Skills are folders, not files — use `references/`, `scripts/`, and `examples/` subdirectories. SKILL.md acts as a table of contents; additional files are only read when needed.

**Test across models.** What works perfectly for Opus might need more detail for Haiku. If you plan to use your skill across models, aim for instructions that work well with all of them.

### SKILL.md Structure

```yaml
---
name: deploy
description: Deploy the application to production. Use when asked to ship, release, or deploy.
context: fork                    # Run in isolated subagent context
agent: general-purpose           # Which subagent type for forked context
disable-model-invocation: true   # Only user can invoke (via /deploy)
allowed-tools: Bash(npm *), Read # Auto-approved tools
model: sonnet                    # Model override
effort: high                     # Reasoning depth
argument-hint: "[environment]"   # Shown in autocomplete
hooks:                           # Skill-scoped hooks
  PreToolUse:
    - matcher: "Bash"
      hooks:
        - type: command
          command: "./validate.sh"
---

Deploy $ARGUMENTS to production:
1. Run test suite
2. Build the application
3. Push to deployment
```

### Dynamic Context Injection

Embed `` !`command` `` to inject shell output at invocation time — Claude runs it before seeing the skill:

```markdown
## Current PR
- Diff: !`gh pr diff`
- Files: !`gh pr diff --name-only`

Summarize the above PR.
```

### String Substitution

```
$ARGUMENTS          # All arguments
$ARGUMENTS[0], $0   # First argument
${CLAUDE_SESSION_ID} # Session ID
${CLAUDE_SKILL_DIR}  # Skill directory path
```

### Controlling Invocation

```yaml
disable-model-invocation: true   # Only you via /skill-name (good for side effects like deploys)
user-invocable: false            # Only Claude automatically (background knowledge)
# Default: both can invoke
```

### Skill Locations (Priority)

| Location | Priority |
|----------|----------|
| Enterprise managed | 1 (highest) |
| `.claude/skills/` (project) | 2 |
| `~/.claude/skills/` (user) | 3 (lowest) |

Skills with the same name: higher priority wins.

### Skills vs Subagents

| Aspect | Skill | Subagent |
|--------|-------|----------|
| Context | Inline (shared) | Isolated (fresh) |
| Invocation | `/name` or auto | `@name` or auto |
| Use case | Reusable prompts/workflows | Complex multi-step tasks |
| Output | Direct in conversation | Summarized on return |

Use skills when you want instructions injected into the current conversation. Use subagents when you want isolated execution with a separate context window.

---

## 3. Agents and Subagents

### What Subagents Are

Subagents are specialized AI assistants that run in isolated contexts with custom system prompts, tool restrictions, and permissions. Each gets a fresh context window — no conversation history carries over.

### Built-in Agent Types

| Agent | Model | Tools | Purpose |
|-------|-------|-------|---------|
| Explore | Haiku | Read-only | Fast codebase search |
| Plan | Inherits | Read-only | Research for plan mode |
| General-purpose | Inherits | All | Complex multi-step tasks |

### Defining Custom Agents

Place in `.claude/agents/` (project) or `~/.claude/agents/` (user):

```yaml
---
name: code-reviewer
description: Reviews code for quality and best practices. Use proactively after code changes.
tools: Read, Grep, Glob, Bash
disallowedTools: Write, Edit
model: sonnet
maxTurns: 50
memory: project
isolation: worktree
---

You are a code reviewer. Analyze code for quality, security, and best practices.
```

### Invoking Agents

- **Natural language**: Name the agent in your prompt
- **@-mention**: `@"code-reviewer (agent)" review auth.ts`
- **Session default**: `claude --agent code-reviewer`
- **Settings default**: `{ "agent": "code-reviewer" }` in settings.json

### Worktree Isolation

Set `isolation: worktree` to give the agent its own filesystem copy. The worktree is cleaned up automatically if no changes are made. Use this for parallel tasks that might conflict.

### Persistent Agent Memory

```yaml
memory: project  # or 'user' or 'local'
```

Agents with memory maintain `MEMORY.md` in a dedicated directory. First 200 lines are loaded at startup.

### Background Agents

Set `background: true` or press **Ctrl+B** to run agents concurrently while you continue working. Background tasks require upfront permission approval.

### Agent Teams

Agent teams coordinate multiple agents working in parallel — each teammate gets a separate session with its own context. Use for large-scale parallel research, review, or implementation.

### Best Practices

- **Prefer Explore agents for search** — they're fast and cheap (Haiku) with read-only access.
- **Use Plan agents for research** — they gather context before you commit to an approach.
- **Restrict tools aggressively** — give agents only what they need. `tools: Read, Grep` is safer than inheriting everything.
- **Use worktree isolation for writes** — prevents agents from stepping on each other's changes.
- **Preload skills into agents** — use `skills: api-conventions` in frontmatter instead of repeating instructions.
- **Agents cannot spawn other agents** — nesting is prevented, so design workflows accordingly.

---

## 4. Hooks

### What Hooks Are

Hooks are user-defined shell commands that execute deterministically at specific points in Claude Code's lifecycle. Unlike the LLM choosing actions, hooks *always* fire when their conditions are met.

### Available Events

| Event | When It Fires |
|-------|--------------|
| `SessionStart` | Session begins |
| `SessionEnd` | Session ends |
| `UserPromptSubmit` | Before processing user input |
| `PreToolUse` | Before a tool executes |
| `PostToolUse` | After a tool executes |
| `PostToolUseFailure` | After a tool fails |
| `PermissionRequest` | When permission is needed |
| `Notification` | When Claude sends a notification |
| `SubagentStart` / `SubagentStop` | Subagent lifecycle |
| `PreCompact` / `PostCompact` | Context compaction |
| `Stop` | When Claude finishes responding |

### Configuration

Configure in settings.json at any scope (user, project, local):

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [
          {
            "type": "command",
            "command": "npx prettier --write $CLAUDE_FILE_PATH"
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "./.claude/hooks/validate-command.sh"
          }
        ]
      }
    ]
  }
}
```

### Hook Types

| Type | Purpose |
|------|---------|
| `command` | Execute a shell script |
| `http` | POST to a remote endpoint |
| `prompt` | Single-turn LLM evaluation |
| `agent` | Multi-turn verification with tool access |

### Exit Codes

- **Exit 0**: Proceed (optionally with structured JSON output)
- **Exit 2**: Block the action (stderr becomes the rejection message)
- **Other codes**: Proceed, stderr is logged

### Common Patterns

- **Auto-format on edit**: `PostToolUse` + `Edit|Write` matcher → run Prettier/Black
- **Block dangerous commands**: `PreToolUse` + `Bash` matcher → validate against deny list
- **Desktop notifications**: `Notification` → trigger OS notification
- **Re-inject context after compaction**: `PostCompact` → echo critical instructions to stdout
- **Audit trail**: `PostToolUse` → log all tool invocations

### Gotchas

- `PreToolUse` hooks fire *before* execution — they cannot see results.
- `PostToolUse` hooks fire *after* execution — they cannot undo file edits.
- `Stop` hooks can create infinite loops if they produce output that triggers another response. Check `stop_hook_active` to guard against this.
- `PermissionRequest` hooks don't fire in headless (`-p`) mode — use `PreToolUse` instead.
- If your shell profile has unconditional `echo` statements, JSON validation in hooks will fail.

---

## 5. Channels

### What Channels Are

Channels are MCP servers that push external events into a running Claude Code session — Slack messages, CI results, webhooks — allowing Claude to react in real time.

### Key Characteristics

- **Push-based**: Events arrive asynchronously (no polling)
- **Bidirectional**: Claude can reply back through the same platform
- **Session-integrated**: Events appear in your existing conversation
- **Secure**: Allowlist-based pairing prevents unauthorized pushes

### Supported Channels

Currently: **Telegram**, **Discord**, **Fakechat** (localhost demo for testing).

### Enabling Channels

```bash
claude --channels plugin:telegram@claude-plugins-official
```

Pairing flow: send message from the platform → receive pairing code → approve in Claude Code.

### Channels vs Other Features

| Feature | Push? | Poll? | Reply goes to |
|---------|-------|-------|---------------|
| Channel | Yes | No | Same platform |
| `/loop` | No | Yes | Terminal |
| MCP server | No | Yes | Terminal |

Use channels when you need Claude to react to external events. Use `/loop` when you need to poll on an interval.

---

## 6. MCP Servers

### What MCP Is

Model Context Protocol (MCP) connects Claude Code to external tools and data sources. MCP servers expose tools, resources, and prompts that Claude can use.

### Configuration

```json
// .mcp.json (project) or ~/.mcp.json (user)
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["@github/mcp-server"],
      "env": { "GITHUB_TOKEN": "ghp_..." }
    }
  }
}
```

Three transport types: **stdio** (local process), **http** (remote), **sse** (streaming).

### Configuration Scopes

| Location | Shared? |
|----------|---------|
| `.mcp.json` | Yes (git) |
| `.mcp.local.json` | No (gitignored) |
| `~/.mcp.json` | No (user-level) |
| Managed settings | IT-deployed |

### Best Practices

- **Keep MCP tool counts low** — many tools consume context and slow discovery.
- **Use `.mcp.local.json`** for tokens and secrets — it's gitignored by default.
- **Scope servers to agents** — not every agent needs every MCP server.
- **Run `/mcp`** to check which servers are loaded and their context cost.
- **Prefer HTTP transport for shared servers** — stdio spawns a process per session.

---

## 7. The Agentic Control Loop

### How Claude Code Works

Claude Code operates in a continuous cycle:

```
Your Prompt
    ↓
[Gather Context] → Read files, search code, understand state
    ↓
[Take Action] → Edit code, run commands, create files
    ↓
[Verify Results] → Run tests, check output, validate
    ↓
Learn & Iterate → Loop back if needed, or return results
```

**Simple control loops outperform multi-agent systems.** LLMs are fragile; additional complexity makes debugging exponentially harder. Reach for subagents and teams only when you have a genuine need for isolation or parallelism.

### Plan Mode

Press **Shift+Tab** twice (or use `--permission-mode plan`) to enter Plan Mode:

1. **Research**: Claude gathers context (read-only tools)
2. **Analysis**: Claude understands requirements
3. **Planning**: Claude creates a detailed plan
4. **Review**: You review and approve
5. **Implementation**: Claude executes with full tool access

Use Plan Mode for unfamiliar codebases, complex refactors, or when you want to review the approach before any files are touched.

### Interruption and Steering

You can interrupt Claude at any point with **Escape**. This is key to efficient use — don't wait for a wrong approach to finish. Interrupt, redirect, and continue.

---

## 8. Context Management

Context management is the single most important skill for effective Claude Code use. Context degradation is the primary failure mode.

### What Consumes Context

- Conversation history (messages + tool results)
- File contents Claude reads
- CLAUDE.md files and auto memory
- MCP tool definitions
- Skill descriptions and loaded skills
- System instructions

### Reducing Context Usage

1. **Keep CLAUDE.md under 200 lines** — move path-specific rules to `.claude/rules/`
2. **Use skills for domain knowledge** — they load on-demand, not every session
3. **Delegate verbose operations to subagents** — their output is summarized on return
4. **Use `/clear` aggressively** — start fresh between unrelated tasks
5. **Scope MCP servers** — don't load tools you won't use

### Auto-Compaction

When context reaches ~95% capacity:
1. Older tool outputs are cleared
2. Conversation is summarized
3. CLAUDE.md is reloaded fresh
4. Key snippets and requests are preserved

You can trigger compaction manually:
- `/compact` — automatic compaction
- `/compact focus on auth` — compact but preserve emphasis on a topic

### Re-injecting Context After Compaction

Instructions given only in conversation (not in CLAUDE.md) are lost after compaction. Use a `PostCompact` hook to re-inject critical instructions:

```json
{
  "hooks": {
    "PostCompact": [{
      "hooks": [{
        "type": "command",
        "command": "cat .claude/post-compact-context.md"
      }]
    }]
  }
}
```

### Monitoring Context

Run `/context` to see a breakdown of what's consuming your context window.

---

## 9. Settings and Permissions

### Configuration Scopes (Priority Order)

1. **Managed policy** — Organization-wide, cannot be overridden
2. **Local** (`.claude/settings.local.json`) — Project-specific, gitignored, highest user priority
3. **Project** (`.claude/settings.json`) — Repository-wide, committed to git
4. **User** (`~/.claude/settings.json`) — All your projects, lowest priority

### Key Settings

```json
{
  "permissions": {
    "defaultMode": "default",
    "allow": ["Bash(npm test *)", "Edit"],
    "deny": ["Bash(rm *)"]
  },
  "model": "sonnet",
  "effort": "medium",
  "hooks": { },
  "agent": "code-reviewer",
  "claudeMdExcludes": ["**/other-team/**"]
}
```

### Permission Rules

- Rules follow glob-like matching: `Bash(npm test *)` matches "npm test foo"
- Trailing space matters: `Bash(npm test *)` ≠ `Bash(npm test*)`
- `allow` auto-approves matching tools; `deny` blocks them entirely

### Verifying Settings

Run `/config` to see active settings and their sources.

---

## 10. Headless and CI Mode

### Running Non-Interactively

```bash
claude -p "Fix the failing tests" --allowedTools "Read,Edit,Bash"
```

Characteristics: no interactive prompts, runs to completion, returns output in specified format.

### Output Formats

```bash
claude -p "Summarize this project" --output-format text    # Plain text (default)
claude -p "Summarize this project" --output-format json    # Structured JSON
claude -p "Summarize this project" --output-format stream-json  # Streaming events
```

### Structured Output

Extract structured data with JSON Schema:

```bash
claude -p "Extract function names from auth.py" \
  --output-format json \
  --json-schema '{"type":"object","properties":{"functions":{"type":"array","items":{"type":"string"}}}}'
```

### Continuing Sessions

```bash
claude -p "Now refactor the API" --continue          # Continue last session
claude -p "Keep going" --resume <session-id>         # Resume specific session
```

### Custom System Prompts

```bash
claude -p "Review this code" --append-system-prompt "You are a security engineer"
claude -p "..." --system-prompt "Fully custom system prompt"
```

### CI/CD Integration

```yaml
# GitHub Actions
- uses: anthropics/claude-code@v0
  with:
    prompt: "Run tests and fix any failures"
    allowed-tools: "Bash,Read,Edit"
```

---

## 11. Custom Commands

### Creating Commands

Custom commands are skills with `disable-model-invocation: true`:

```yaml
# .claude/skills/deploy/SKILL.md
---
name: deploy
description: Deploy application to production
disable-model-invocation: true
argument-hint: "[environment]"
---

Deploy to $ARGUMENTS:
1. Run tests
2. Build
3. Push
```

Invoke with `/deploy production`.

### Legacy Commands

The older `.claude/commands/name.md` format still works but lacks frontmatter support. Migrate to `.claude/skills/` for hooks, supporting files, and directory organization.

### MCP Prompts as Commands

MCP servers can expose prompts invocable as `/mcp-server:prompt-name [arguments]`.

---

## 12. IDE Integrations

### VS Code

- Prompt box in sidebar: **Cmd+Shift+L**
- Reference files with `@` syntax
- Resume previous conversations
- Multiple concurrent conversations
- Full MCP integration

### JetBrains

- IntelliJ IDEA, PyCharm, WebStorm, GoLand, etc.
- Prompt box in IDE, file references
- Remote development and WSL support

---

## 13. Meta-Principles

**Context management is paramount.** The most successful Claude Code users obsessively manage context through lean CLAUDE.md files, aggressive `/clear` usage, skills for on-demand knowledge, and subagents for isolation. Context degradation is the primary failure mode.

**Simple control loops outperform multi-agent systems.** LLMs are fragile; additional complexity makes debugging exponentially harder. Use the simplest approach that works: direct prompting > skills > subagents > agent teams.

**CLAUDE.md is for rules; skills are for knowledge.** CLAUDE.md loads every session — only include things that apply broadly. For domain knowledge or workflows that are only relevant sometimes, use skills instead.

**Hooks are for determinism; prompts are for judgment.** If something must *always* happen (formatting, validation, notifications), use a hook. If something requires *judgment* (code review, refactoring decisions), let Claude decide.

**Scope everything as narrowly as possible.** Path-specific rules over global CLAUDE.md. Restricted tool lists over full access. Project-scoped MCP over user-scoped. Local settings over shared settings. The narrower the scope, the less noise in every session.

**Iterate on your configuration.** Treat CLAUDE.md, skills, hooks, and agent definitions like code. When Claude misbehaves, check whether your configuration is the problem before blaming the model. Prune, test, and version-control your guidance files.
