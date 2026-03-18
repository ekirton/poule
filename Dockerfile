# ============================================================================
# Stage 1: coq-base — Coq/Rocq toolchain (cached aggressively)
# Rebuilds only when Coq version changes.
# ============================================================================
FROM python:3.11-slim-bookworm AS coq-base

RUN apt-get update && apt-get install -y --no-install-recommends \
        bubblewrap \
        bzip2 \
        mercurial \
        darcs \
        gcc \
        g++ \
        libc6-dev \
        libgmp-dev \
        pkg-config \
        make \
        m4 \
        unzip \
        curl \
        git \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install opam (OCaml package manager)
RUN curl -fsSL https://raw.githubusercontent.com/ocaml/opam/master/shell/install.sh | \
        bash -s -- --no-backup

# Initialize opam without sandboxing (runs inside container already)
RUN opam init --disable-sandboxing --auto-setup --bare && \
    opam repository add --all default https://opam.ocaml.org

# Create OCaml switch and install Coq + coq-lsp
RUN opam switch create coq ocaml-base-compiler.4.14.2 && \
    eval $(opam env --switch=coq) && \
    opam repo add coq-released https://coq.inria.fr/opam/released --all-switches && \
    opam install -y coq.8.19.2 coq-lsp coq-hammer coq-dpdgraph dune && \
    opam clean -a -c -s --logs

# Move opam to /opt so it's accessible to any user,
# then rewrite hardcoded /root/.opam paths so ocamlfind and coq-lsp work
# for non-root users.
RUN mv /root/.opam /opt/opam && chmod -R a+rX /opt/opam && \
    find /opt/opam -type f \( -name "*.conf" -o -name "*.config" -o -name "*.install" \) \
         -exec sed -i 's|/root/\.opam|/opt/opam|g' {} + && \
    printf 'stdlib="/opt/opam/coq/lib/ocaml"\n' >> /opt/opam/coq/lib/findlib.conf
ENV OPAMROOT=/opt/opam
ENV OCAMLFIND_CONF=/opt/opam/coq/lib/findlib.conf
# COQLIB: tells coq-lsp where the Coq standard library lives (path is baked
# into the compiled coq binary at /root/.opam/... but opam was moved to /opt).
ENV COQLIB=/opt/opam/coq/lib/coq
ENV PATH="/opt/opam/coq/bin:${PATH}"

# ============================================================================
# Stage 2: app-deps — System packages + Python dependencies + Claude Code
# Rebuilds only when lockfiles change (or Claude Code version bumps).
# Claude Code is installed last so daily version bumps only invalidate this
# one layer — the Coq toolchain and Python deps stay cached.
# ============================================================================
FROM coq-base AS app-deps

# Accept host user info as build args for proper file ownership
ARG HOST_UID=1000
ARG HOST_GID=1000
ARG HOST_USER=poule
ARG HOST_GROUP=poule

# Install Node.js, Charm repo (for glow), and interactive tools
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://repo.charm.sh/apt/gpg.key | gpg --dearmor -o /etc/apt/keyrings/charm.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" \
        > /etc/apt/sources.list.d/charm.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        nodejs \
        zsh \
        sudo \
        less \
        openssh-client \
        gnupg2 \
        gh \
        jq \
        wget \
        rsync \
        vim \
        emacs-nox \
        ripgrep \
        fd-find \
        bat \
        glow \
        sqlite3 \
        locales \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Configure UTF-8 locale
RUN sed -i '/en_US.UTF-8/s/^# //g' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Create user matching host
RUN (getent group ${HOST_GID} >/dev/null 2>&1 || groupadd -g ${HOST_GID} ${HOST_GROUP}) && \
    useradd -m -u ${HOST_UID} -g ${HOST_GID} -s /bin/zsh ${HOST_USER}

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /poule

# Copy only dependency manifests to cache the deps layer
COPY pyproject.toml uv.lock ./

# Install MCP server management script (available in both dev and production images)
COPY docker/poule-mcp /usr/local/bin/poule-mcp
RUN chmod +x /usr/local/bin/poule-mcp

# Place the virtualenv outside /app so it survives a bind-mount of the
# project root in dev containers.
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
RUN mkdir -p /opt/venv && chown -R ${HOST_UID}:${HOST_GID} /opt/venv /poule

# Create venv as the app user so it's writable when source is installed later
USER ${HOST_USER}
RUN uv sync --frozen --group dev
USER root

ENV PATH="/opt/venv/bin:${PATH}"

# ── Claude Code: baked into image for instant startup ──────────────────────
# CLAUDE_CODE_VERSION and CACHEBUST_CLAUDE are declared here (not at the top)
# so changing the version only invalidates this final layer, keeping all the
# toolchain and dependency layers above fully cached.  Claude updates daily;
# this placement keeps rebuilds under 60 seconds.
ARG CLAUDE_CODE_VERSION=latest
ARG CACHEBUST_CLAUDE=0
USER ${HOST_USER}
RUN curl -fsSL https://claude.ai/install.sh | bash -s ${CLAUDE_CODE_VERSION}
USER root
RUN mv /home/${HOST_USER}/.local/share/claude /opt/claude \
    && ln -sf "$(ls -d /opt/claude/versions/* | head -1)" /usr/local/bin/claude \
    && chown -R ${HOST_USER}:${HOST_GROUP} /opt/claude
LABEL claude.code.version=${CLAUDE_CODE_VERSION}

# ============================================================================
# Stage 3: runtime — Application code + entrypoint
# Rebuilds on every source change (fast — just file copies).
# Claude Code is inherited from app-deps (already in /opt/claude).
# ============================================================================
FROM app-deps AS runtime

ARG HOST_UID=1000
ARG HOST_GID=1000
ARG HOST_USER=poule

COPY --chown=${HOST_UID}:${HOST_GID} src/ src/
COPY --chown=${HOST_UID}:${HOST_GID} test/ test/
COPY --chown=${HOST_UID}:${HOST_GID} examples/ examples/
COPY --chown=${HOST_UID}:${HOST_GID} commands/ commands/
COPY --chown=${HOST_UID}:${HOST_GID} .mcp.json CLAUDE.md README.md ./

USER ${HOST_USER}

# Minimal zshrc (overridden by persistent home mount at runtime)
RUN cat > ~/.zshrc << 'ZSHEOF'
setopt PROMPT_SUBST
_git_branch_colored() {
  local branch=$(git branch --show-current 2>/dev/null)
  if [ -n "$branch" ]; then
    if [ "$branch" = "main" ]; then
      echo "%F{red}[$branch]%f"
    else
      echo "%F{green}[$branch]%f"
    fi
  fi
}
PROMPT='%F{cyan}[poule]%f $(_git_branch_colored)%F{blue}[%~]%f$ '
HISTFILE=~/.zsh_history
HISTSIZE=10000
SAVEHIST=10000
export PATH="/opt/opam/coq/bin:$HOME/.local/bin:$PATH"
export UV_LINK_MODE="copy"
alias claude='claude --dangerously-skip-permissions'
ZSHEOF

VOLUME ["/data"]
EXPOSE 3000
ENV SHELL=/bin/zsh

USER root
COPY docker/entrypoint.sh /usr/local/bin/poule-entrypoint
RUN chmod +x /usr/local/bin/poule-entrypoint
USER ${HOST_USER}

ENTRYPOINT ["/usr/local/bin/poule-entrypoint"]
