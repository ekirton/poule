# Installation

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- Coq/Rocq 8.19+ with coq-lsp or SerAPI

## Coq Toolchain

Install [opam](https://opam.ocaml.org/), then:

```bash
opam init
opam install coq coq-lsp
opam repo add coq-released https://coq.inria.fr/opam/released
opam install coq-mathcomp-ssreflect   # optional, for MathComp indexing
eval $(opam env)
```

See the [opam install guide](https://opam.ocaml.org/doc/Install.html) for platform-specific opam installation (macOS via Homebrew, Linux distros, WSL2).

## Python Package

```bash
git clone https://github.com/ekirton/poule.git
cd poule
uv sync
```

## Docker

The Docker image bundles Coq, Python, Claude Code, and all dependencies — no local Coq or opam installation required.

```bash
git clone https://github.com/ekirton/poule.git
cd poule
docker build -t poule .
```

Download the prebuilt index into a local data directory:

```bash
mkdir -p data
docker run --rm -v ./data:/data --entrypoint uv poule \
  run python -m poule.cli download-index --output /data/index.db
```

The image supports two usage modes:

**MCP server only** — run Claude Code on the host and connect to the containerized server. Add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "coq-search": {
      "command": "docker",
      "args": ["run", "--rm", "-i", "-v", "/path/to/data:/data", "poule"]
    }
  }
}
```

**Fully containerized** — run Claude Code inside the container alongside the MCP server:

```bash
docker run --rm -it \
  -e ANTHROPIC_API_KEY \
  -v ./data:/data \
  --entrypoint claude \
  poule
```

This starts Claude Code with the Coq toolchain, MCP server, and index all available inside the container. Configure the MCP server in the container's Claude Code settings (`/claude mcp add`) or mount a config file:

```bash
docker run --rm -it \
  -e ANTHROPIC_API_KEY \
  -v ./data:/data \
  -v ./mcp.json:/root/.claude/mcp.json:ro \
  --entrypoint claude \
  poule
```

Where `mcp.json` points to the in-container paths:

```json
{
  "mcpServers": {
    "coq-search": {
      "command": "uv",
      "args": ["run", "--project", "/app", "python", "-m", "poule.server", "--db", "/data/index.db"]
    }
  }
}
```

## Getting the Search Index

**Option A — Download the prebuilt index** (no Coq installation required):

```bash
uv run python -m poule.cli download-index
```

To also download the neural premise selection model:

```bash
uv run python -m poule.cli download-index --include-model
```

You can also download manually from [GitHub Releases](https://github.com/ekirton/poule/releases).

**Option B — Build from source** (requires Coq toolchain):

```bash
uv run python -m poule.extraction --target stdlib+mathcomp --db index.db --progress
```

## Configure Claude Code

Add to `~/.claude/mcp.json`:

```json
{
  "mcpServers": {
    "coq-search": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/poule", "python", "-m", "poule.server", "--db", "/path/to/poule/index.db"]
    },
    "mermaid": {
      "command": "npx",
      "args": ["-y", "@mermaidchart/mcp-server"]
    }
  }
}
```

Replace `/path/to/poule` with the absolute path to your clone.
