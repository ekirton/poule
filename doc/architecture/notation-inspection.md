# Notation Inspection

How the MCP server wraps Coq's notation-related vernacular commands to support notation lookup, scope inspection, ambiguity resolution, precedence/associativity extraction, and authoring guidance.

**Feature**: [Notation Inspection](../features/notation-inspection.md)
**Integration point**: [MCP Server](mcp-server.md), [Vernacular Introspection](../features/vernacular-introspection.md) (shared `coq_query` tool)

---

## Component Diagram

```
Claude Code / LLM
  │
  │ MCP tool call: coq_query(command="print_notation" | "locate_notation" |
  │                           "print_scope" | "print_visibility", ...)
  ▼
┌────────────────────────────────────────────────────────────────────────┐
│ MCP Server                                                             │
│                                                                        │
│  coq_query tool (shared with Vernacular Introspection)                │
│    │                                                                   │
│    ├─ command ∈ {print, check, about, locate, search, compute, eval}  │
│    │   → Vernacular Introspection path (existing)                     │
│    │                                                                   │
│    ├─ command ∈ {print_notation, locate_notation,                      │
│    │             print_scope, print_visibility}                        │
│    │   → Notation Inspection path (this document)                     │
│    │                                                                   │
│    ▼                                                                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │ Notation Query Dispatcher                                        │  │
│  │                                                                  │  │
│  │  1. Normalize user input (quoting, underscore placeholders)     │  │
│  │  2. Build vernacular command string                              │  │
│  │  3. Submit to Coq backend via Proof Session Manager              │  │
│  │  4. Parse raw output into structured data                        │  │
│  │  5. Resolve ambiguities (multi-scope matches)                   │  │
│  │  6. Return structured response                                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│           │                                                            │
│           │ vernacular command string                                   │
│           ▼                                                            │
│  Proof Session Manager (reused — same as vernacular introspection)    │
│           │                                                            │
│           │ coq-lsp / SerAPI                                           │
│           ▼                                                            │
│  Coq Backend Process                                                   │
└────────────────────────────────────────────────────────────────────────┘
```

Notation inspection does not introduce a new MCP tool. It extends the existing `coq_query` tool with additional `command` variants. The Notation Query Dispatcher is a logical subcomponent within the `coq_query` handler, not a separate process or service.

---

## Command Mapping

Each notation query maps to one or more Coq vernacular commands. The dispatcher constructs the command string, handles quoting, and submits it to the Coq backend.

| Subcommand | Coq Vernacular | Purpose |
|------------|---------------|---------|
| `print_notation` | `Print Notation "⟨notation_string⟩".` | Retrieve the expansion (underlying Coq term), precedence, associativity, format string, and flags for a notation |
| `locate_notation` | `Locate "⟨notation_string⟩".` | Find the defining module(s) and scope(s) for a notation |
| `print_scope` | `Print Scope ⟨scope_name⟩.` | List all notations registered in a given scope |
| `print_visibility` | `Print Visibility.` | Show all open scopes and their stacking order |

### Input normalization

Users provide notation strings in surface syntax. The dispatcher transforms them before submission:

1. **Underscore insertion** — if the user provides a notation without explicit placeholder underscores (e.g., `++` instead of `_ ++ _`), the dispatcher infers arity from context and inserts `_` placeholders at operand positions.
2. **Quote escaping** — the notation string is wrapped in double quotes with internal double quotes escaped, matching the quoting convention expected by `Locate` and `Print Notation`.
3. **Whitespace normalization** — leading/trailing whitespace is stripped; internal whitespace is collapsed to single spaces.

When the user provides a Coq term rather than a bare notation string, the dispatcher first issues a `Locate` command to identify which notation was used, then follows up with `Print Notation` to retrieve the full details. This two-step resolution is transparent to the caller.

---

## Output Parsing

Each command type produces distinct raw output that must be parsed into structured data.

### Print Notation

Raw output format (Coq 8.19+):

```
"⟨notation_string⟩" := ⟨expansion⟩
  (at level ⟨N⟩, ⟨arg₁⟩ at level ⟨M⟩, ..., ⟨assoc⟩ associativity)
  : ⟨scope⟩
```

Parsed fields:

| Field | Extraction rule |
|-------|----------------|
| `notation_string` | Text between opening and closing double quotes on the first line |
| `expansion` | Text after `:=` on the first line, trimmed |
| `level` | Integer following `at level` |
| `arg_levels` | List of `(placeholder, level)` pairs from `⟨argN⟩ at level ⟨M⟩` fragments |
| `associativity` | One of `left`, `right`, `no` — extracted from the word preceding `associativity` |
| `format` | If a `format` clause is present, the format string; otherwise absent |
| `scope` | Scope name following the `:` on the scope line |
| `only_parsing` | Boolean — true if `(only parsing)` appears |
| `only_printing` | Boolean — true if `(only printing)` appears |

### Locate Notation

Raw output format:

```
Notation "⟨notation_string⟩" := ⟨expansion⟩ : ⟨scope⟩
  (default interpretation)
```

When multiple scopes define the notation, multiple blocks appear. The block marked `(default interpretation)` is the currently active one.

Parsed fields per entry:

| Field | Extraction rule |
|-------|----------------|
| `notation_string` | Text between quotes after `Notation` |
| `expansion` | Text after `:=` up to `:` scope delimiter |
| `scope` | Scope name following `:` |
| `is_default` | Boolean — true if `(default interpretation)` follows the entry |

### Print Scope

Raw output format:

```
⟨scope_name⟩
"⟨notation₁⟩" := ⟨expansion₁⟩
"⟨notation₂⟩" := ⟨expansion₂⟩
...
```

The first line is the scope name. Each subsequent non-empty line is a notation entry. Parsed into a list of `(notation_string, expansion)` pairs keyed under the scope name.

### Print Visibility

Raw output format:

```
⟨scope₁⟩ (bound to ⟨type₁⟩)
⟨scope₂⟩
⟨scope₃⟩ (bound to ⟨type₃⟩)
...
```

Scopes are listed in priority order (highest priority first). Some scopes carry a type binding. Parsed into an ordered list of `(scope_name, bound_type_or_null)` pairs.

---

## Ambiguity Resolution

When a notation has interpretations in multiple open scopes, the dispatcher:

1. Issues `Locate "⟨notation_string⟩".` to retrieve all interpretations across scopes.
2. Issues `Print Visibility.` to retrieve the current scope stacking order.
3. Matches each interpretation's scope against the visibility order to determine which is active.
4. Annotates each interpretation with its priority rank and whether it is the active interpretation.
5. For the active interpretation, includes the reason: either "highest-priority open scope" or "type-directed scope binding on ⟨type⟩".

The result is a `NotationAmbiguity` structure (see Data Structures below) containing all interpretations in priority order, with the active one marked.

When only one interpretation exists in scope, the ambiguity structure is omitted and the single `NotationInfo` is returned directly.

---

## Precedence and Associativity Extraction

Precedence and associativity are extracted from the `Print Notation` output as part of the standard parse (see Output Parsing above). The extracted values are:

- **Level**: integer 0–200 inclusive. Lower levels bind tighter.
- **Associativity**: one of `left`, `right`, `none`.
- **Argument levels**: per-placeholder binding levels that constrain how tightly sub-expressions within the notation bind. An argument at level 0 accepts only atomic terms; an argument at level 200 accepts any expression.
- **Format string**: optional layout directive controlling how the notation is pretty-printed.
- **Flags**: `only_parsing` (notation accepted as input but not used in output) and `only_printing` (notation used in output but not accepted as input).

These fields are included in every `NotationInfo` response, enabling Claude to explain parsing behavior by comparing levels and associativity across notations.

---

## Data Structures

All structures are language-agnostic. Field types use domain-level descriptions.

### NotationInfo

| Field | Type | Description |
|-------|------|-------------|
| `notation_string` | string | The notation pattern with placeholders (e.g., `_ ++ _`) |
| `expansion` | string | The underlying Coq term the notation desugars to |
| `level` | integer (0–200) | Precedence level |
| `associativity` | `"left"` or `"right"` or `"none"` | Associativity |
| `arg_levels` | list of (string, integer) | Per-placeholder name and binding level |
| `format` | string or null | Format string if defined |
| `scope` | string | Scope the notation is registered in |
| `defining_module` | string or null | Fully qualified module path where the notation is defined (from `Locate`) |
| `only_parsing` | boolean | True if the notation is accepted as input only |
| `only_printing` | boolean | True if the notation is used in output only |

### ScopeInfo

| Field | Type | Description |
|-------|------|-------------|
| `scope_name` | string | Name of the scope |
| `bound_type` | string or null | Type this scope is bound to (for type-directed resolution), or null |
| `notations` | list of NotationInfo | All notations registered in this scope (populated by `print_scope`) |

### NotationAmbiguity

| Field | Type | Description |
|-------|------|-------------|
| `notation_string` | string | The ambiguous notation pattern |
| `interpretations` | list of NotationInterpretation | All interpretations in priority order |
| `active_index` | integer | Index into `interpretations` identifying the currently active one |
| `resolution_reason` | string | Why the active interpretation was selected (e.g., "highest-priority open scope" or "type-directed binding on nat") |

### NotationInterpretation

| Field | Type | Description |
|-------|------|-------------|
| `expansion` | string | The Coq term this interpretation expands to |
| `scope` | string | Scope providing this interpretation |
| `defining_module` | string or null | Module where this interpretation is defined |
| `priority_rank` | integer | Position in the scope stacking order (0 = highest priority) |

---

## Integration with Vernacular Introspection

Notation inspection is not a standalone tool. It extends the `coq_query` tool defined by vernacular introspection with four additional `command` values: `print_notation`, `locate_notation`, `print_scope`, `print_visibility`.

Shared infrastructure:

- **Coq backend communication** — notation commands are submitted through the same Proof Session Manager path used by `print`, `check`, `about`, `locate`, `search`, `compute`, and `eval`. No separate connection or session is needed.
- **Session awareness** — notation commands execute against the current Coq environment, including any active proof session. The set of open scopes and available notations reflects the current state of `Require Import` and `Open Scope` commands in the loaded file.
- **Error propagation** — Coq-level errors (syntax errors, unknown scopes, backend crashes) are caught and translated to structured error responses using the same error contract as other `coq_query` commands.

Notation-specific additions:

- **Input normalization** — the notation dispatcher applies quoting and placeholder insertion before submission (not needed for other `coq_query` commands).
- **Output parsing** — each notation command has a dedicated parser that extracts structured fields from the raw textual output. Other `coq_query` commands return raw text.
- **Ambiguity resolution** — the notation dispatcher may chain multiple vernacular commands (Locate + Print Visibility) to resolve ambiguities, whereas other `coq_query` commands are single-shot.

---

## Error Handling

| Condition | Error Code | Message |
|-----------|-----------|---------|
| Notation string does not match any in-scope notation | `NOTATION_NOT_FOUND` | Notation `"⟨notation_string⟩"` not found in the current environment. |
| Scope name does not match any registered scope | `SCOPE_NOT_FOUND` | Scope `⟨scope_name⟩` is not registered in the current environment. |
| No Coq session active (no file loaded) | `SESSION_NOT_FOUND` | No active Coq session. Load a file first. |
| Coq backend crashed during command execution | `BACKEND_CRASHED` | The Coq backend has crashed. Close the session and open a new one. |
| Malformed notation string (unparseable after normalization) | `PARSE_ERROR` | Failed to parse notation string: `⟨details⟩` |
| Coq command returned output that could not be parsed | `PARSE_ERROR` | Failed to parse Coq output for `⟨command⟩`: `⟨details⟩` |
| Print Notation not available (Coq < 8.19) | `UNSUPPORTED_COMMAND` | `Print Notation` requires Coq 8.19 or later. Use `Locate` as a fallback. |

Error responses use the same MCP error format as the rest of the MCP server (see [mcp-server.md](mcp-server.md) § Error Contract).

---

## Design Rationale

### Why extend coq_query rather than add separate tools

The feature document identifies notation commands as closely related to the existing vernacular introspection commands: they share the same execution path (submit a vernacular string, receive textual output), the same session-awareness requirements, and the same error modes. Adding four separate tools would consume tool count budget and fragment a conceptually unified interface. Extending `coq_query` with additional `command` values keeps the interface consistent: one tool for read-only queries against the Coq environment.

### Why parse output rather than use a structured API

Coq does not expose notation metadata through a structured API. The vernacular commands (`Print Notation`, `Locate`, `Print Scope`, `Print Visibility`) return human-readable text. Parsing this text is fragile relative to a structured API but is the only option without modifying Coq itself, which is out of scope. The parsing layer is isolated behind the dispatcher so that changes to Coq's output format require updates in one place.

### Why two-step resolution for term-based queries

When a user provides a term rather than a bare notation string, the dispatcher must first identify which notation was used. Issuing `Locate` on the term's surface syntax identifies the notation and its scope, after which `Print Notation` retrieves the full metadata. This two-step approach avoids requiring the user to isolate the notation manually — they can point at a line of code and ask "what does this mean?" The cost is one additional round-trip to the Coq backend, which is negligible relative to the 2-second latency budget.

### Why include all interpretations for ambiguous notations

The PRD requires disambiguation (RN-P1-3), and the feature document describes listing all interpretations with the active one marked. Returning only the active interpretation would answer "what does this mean now?" but not "why did Coq pick this one?" or "how do I get a different one?" Including all interpretations with priority ranks enables Claude to explain scope resolution and suggest `%scope_key` overrides in a single response.

### Why normalize input rather than require exact quoting

Coq's notation commands expect notation strings in a specific quoting format that differs from the surface syntax. Users rarely know the correct quoting. The PRD (RN-P0-1) and feature document both specify that quoting is handled internally. Input normalization — inserting placeholders, escaping quotes, normalizing whitespace — removes this barrier at the cost of a heuristic that may occasionally fail for exotic notations. When normalization fails, the error is reported with the original and normalized strings so the user can correct manually.
