# Fill Admits Orchestrator

Batch automation component that scans a Coq proof script for `admit` calls, opens proof sessions at each location, invokes proof search, and assembles a modified script with filled admits.

**Architecture**: [fill-admits-orchestrator.md](../doc/architecture/fill-admits-orchestrator.md), [component-boundaries.md](../doc/architecture/component-boundaries.md), [proof-types.md](../doc/architecture/data-models/proof-types.md)

---

## 1. Purpose

Define the fill-admits orchestrator that locates `admit` calls in a .v file, opens a proof session for each, invokes the Proof Search Engine to find a replacement, and assembles the modified script with per-admit outcome reporting.

## 2. Scope

**In scope**: Admit location (syntactic scanning), per-admit session lifecycle, proof search invocation per admit, script assembly with replacements, result reporting (filled/unfilled counts, per-admit details).

**Out of scope**: Search algorithm (owned by proof-search-engine), session management (owned by proof-session), MCP protocol handling (owned by mcp-server), proof state serialization (owned by proof-serialization).

## 3. Definitions

| Term | Definition |
|------|-----------|
| Admit | An `admit.` or `Admitted.` call in a Coq proof script that marks an unproven obligation |
| Admit location | The syntactic position of an admit call: proof name, index within proof, line number, column range |
| Fill | Replacing an admit with a verified tactic sequence that closes the sub-goal |
| Sketch-then-prove | A usage pattern where the user writes a proof with deliberate admit stubs, then invokes fill-admits to attempt filling each |

## 4. Behavioral Requirements

### 4.1 Entry Point

#### fill_admits(file_path, timeout_per_admit, max_depth, max_breadth)

- REQUIRES: `file_path` is a non-empty string referencing an existing .v file. `timeout_per_admit` is a positive number (seconds), default 30. `max_depth` is a positive integer, default 10. `max_breadth` is a positive integer, default 20.
- ENSURES: Reads the file, locates all admit calls, attempts to fill each via proof search, and returns a FillAdmitsResult containing per-admit outcomes and the modified script.
- On file not found: returns `FILE_NOT_FOUND` error immediately.
- On no admits found: returns a FillAdmitsResult with `total_admits = 0`, `filled = 0`, `unfilled = 0`, empty `results` list, and the unmodified file contents as `modified_script`.

> **Given** a .v file containing two proofs, each with one `admit.`
> **When** `fill_admits(file_path)` is called
> **Then** two proof searches are executed (one per admit), and the result indicates which were filled

> **Given** a .v file with no `admit` calls
> **When** `fill_admits(file_path)` is called
> **Then** a FillAdmitsResult with `total_admits = 0` is returned with the unmodified script

> **Given** a file path that does not exist
> **When** `fill_admits(file_path)` is called
> **Then** a `FILE_NOT_FOUND` error is returned

### 4.2 Admit Location

The orchestrator shall locate admits by syntactic scanning of the file contents.

#### locate_admits(file_contents)

- REQUIRES: `file_contents` is a string.
- ENSURES: Returns an ordered list of AdmitLocation objects, sorted by line number (ascending). Each AdmitLocation identifies one `admit.` or `Admitted.` call.
- The scanner shall match `admit.` and `Admitted.` tokens (case-sensitive, Coq conventions). Occurrences inside comments (`(* ... *)`) shall be excluded.
- MAINTAINS: The order of returned AdmitLocations matches their order of appearance in the file.

> **Given** a file with `admit.` at line 10 and `Admitted.` at line 25
> **When** `locate_admits` runs
> **Then** two AdmitLocation objects are returned: `{line_number: 10, ...}` and `{line_number: 25, ...}`

> **Given** a file with `(* admit. *)` inside a comment
> **When** `locate_admits` runs
> **Then** no AdmitLocation is returned for the commented occurrence

> **Given** a file with no admit calls
> **When** `locate_admits` runs
> **Then** an empty list is returned

### 4.3 Per-Admit Processing

For each admit in source order, the orchestrator shall:

1. Open a proof session at the admit's `proof_name`.
2. Navigate to the admit's position by stepping forward through the proof's tactic sequence until reaching the proof state just before the admit.
3. Invoke `proof_search(session_id, timeout_per_admit, max_depth, max_breadth)`.
4. Record the result.
5. Close the proof session.

- MAINTAINS: Each admit is processed with a fresh, independent proof session. A failure or crash during one admit's processing does not affect subsequent admits.

> **Given** a proof with tactics `[intro n., simpl., admit., reflexivity.]` and the admit is at index 2
> **When** the orchestrator processes this admit
> **Then** it opens a session, steps forward twice (executing `intro n.` and `simpl.`), then invokes proof search on the resulting proof state

> **Given** a proof session fails to open (proof not found)
> **When** the orchestrator processes this admit
> **Then** it records an error for this admit and proceeds to the next admit

> **Given** the Coq backend crashes during proof search for admit at line 15
> **When** the orchestrator processes subsequent admits
> **Then** subsequent admits are processed normally with fresh sessions

### 4.4 Script Assembly

After all admits are processed, the orchestrator shall assemble the modified script:

1. For each successfully filled admit, replace the admit text span (line_number, column_range) with the verified tactic sequence from the SearchResult's proof_script.
2. For unfilled admits, leave the original `admit.` or `Admitted.` text unchanged.
3. Replacements shall be applied from last to first (reverse source order) to preserve line numbers for earlier replacements.

- MAINTAINS: The modified script is a valid text replacement of the original file. No content outside of admit text spans is modified.

> **Given** admits at lines 10 and 25, where line 10 is filled with `[reflexivity.]` and line 25 is unfilled
> **When** the script is assembled
> **Then** `admit.` at line 10 is replaced with `reflexivity.`, and `admit.` at line 25 remains unchanged

> **Given** an admit filled with a multi-tactic proof `[intro n., simpl., reflexivity.]`
> **When** the replacement is inserted
> **Then** the admit is replaced with `intro n. simpl. reflexivity.` (or equivalent formatted tactic sequence)

## 5. Data Model

### AdmitLocation

| Field | Type | Constraints |
|-------|------|-------------|
| `proof_name` | qualified name | Required; fully qualified name of the proof containing this admit |
| `admit_index` | non-negative integer | Required; 0-based index of this admit within its proof |
| `line_number` | positive integer | Required; 1-based source line number |
| `column_range` | (start: non-negative integer, end: non-negative integer) | Required; byte offsets of the admit text within the line |

### FillAdmitsResult

| Field | Type | Constraints |
|-------|------|-------------|
| `total_admits` | non-negative integer | Required; total admits found in the file |
| `filled` | non-negative integer | Required; admits successfully replaced; `filled ≤ total_admits` |
| `unfilled` | non-negative integer | Required; admits not filled; `unfilled = total_admits - filled` |
| `results` | ordered list of AdmitResult | Required; one per admit, in source order |
| `modified_script` | text | Required; the file contents with filled admits replaced |

### AdmitResult

| Field | Type | Constraints |
|-------|------|-------------|
| `proof_name` | qualified name | Required |
| `admit_index` | non-negative integer | Required |
| `line_number` | positive integer | Required |
| `status` | `"filled"` or `"unfilled"` | Required |
| `replacement` | ordered list of string or null | On `"filled"`: the verified tactic sequence. On `"unfilled"`: null. |
| `search_stats` | object or null | On `"unfilled"`: `{ states_explored, unique_states, wall_time_ms }` from the SearchResult. On `"filled"`: null. |
| `error` | string or null | Non-null when the admit could not be processed at all (session open failure, backend crash). Null otherwise. |

## 6. Interface Contracts

### Fill Admits Orchestrator → Proof Session Manager

| Property | Value |
|----------|-------|
| Operations used | `create_session`, `step_forward`, `close_session` |
| Lifecycle | One session per admit; created and closed within per-admit loop |
| Error strategy | `FILE_NOT_FOUND` or `PROOF_NOT_FOUND` → record error in AdmitResult, continue. `BACKEND_CRASHED` → record error in AdmitResult, continue. |
| Concurrency | Sequential — one session at a time |

### Fill Admits Orchestrator → Proof Search Engine

| Property | Value |
|----------|-------|
| Operations used | `proof_search(session_id, timeout, max_depth, max_breadth)` |
| Input | Session ID positioned at the admit's proof state |
| Output | SearchResult |
| Error strategy | Search failure → record `"unfilled"` in AdmitResult with search stats. Search success → record `"filled"` with replacement tactics. |

## 7. Error Specification

### 7.1 Input Errors

| Condition | Behavior |
|-----------|----------|
| `file_path` does not exist | Return `FILE_NOT_FOUND` error immediately |
| `file_path` is empty | Return `FILE_NOT_FOUND` error immediately |
| `timeout_per_admit` ≤ 0 | Clamp to 1 second |
| `max_depth` ≤ 0 | Clamp to 1 |
| `max_breadth` ≤ 0 | Clamp to 1 |

### 7.2 Per-Admit Errors

| Condition | Behavior |
|-----------|----------|
| Proof not found for admit | Record AdmitResult with `status = "unfilled"` and `error` describing the failure. Continue with next admit. |
| Backend crash during session open or search | Record AdmitResult with `status = "unfilled"` and `error` describing the crash. Continue with next admit. |
| Proof search returns `status = "failure"` | Record AdmitResult with `status = "unfilled"` and `search_stats`. Continue with next admit. |
| Step forward fails during navigation to admit position | Record AdmitResult with `status = "unfilled"` and `error`. Close session. Continue with next admit. |

### 7.3 Aggregate Outcomes

| Condition | Behavior |
|-----------|----------|
| All admits filled | Return FillAdmitsResult with `filled = total_admits`, `unfilled = 0` |
| No admits filled | Return FillAdmitsResult with `filled = 0`, `unfilled = total_admits` |
| No admits found | Return FillAdmitsResult with `total_admits = 0` and unmodified script |

## 8. Non-Functional Requirements

- Per-admit processing time is bounded by `timeout_per_admit` plus session open/close overhead (~1-2 seconds).
- Total processing time is bounded by `total_admits * (timeout_per_admit + session_overhead)`.
- Memory usage is bounded by one proof session at a time plus the file contents and result accumulator.
- The orchestrator shall not modify the original file on disk. The modified script is returned in the result only.

## 9. Examples

### Two admits, one filled

```
fill_admits(file_path="/path/to/example.v", timeout_per_admit=30)

File contents:
  Lemma foo : 0 + 0 = 0. Proof. admit. Qed.
  Lemma bar : forall n, complex n. Proof. admit. Qed.

Processing:
  Admit 1 (foo, line 1): search finds "reflexivity." → filled
  Admit 2 (bar, line 2): search times out → unfilled

Result:
{
  "total_admits": 2,
  "filled": 1,
  "unfilled": 1,
  "results": [
    {"proof_name": "foo", "admit_index": 0, "line_number": 1, "status": "filled", "replacement": ["reflexivity."], "search_stats": null, "error": null},
    {"proof_name": "bar", "admit_index": 0, "line_number": 2, "status": "unfilled", "replacement": null, "search_stats": {"states_explored": 200, "unique_states": 150, "wall_time_ms": 30000}, "error": null}
  ],
  "modified_script": "Lemma foo : 0 + 0 = 0. Proof. reflexivity. Qed.\nLemma bar : forall n, complex n. Proof. admit. Qed."
}
```

### No admits found

```
fill_admits(file_path="/path/to/clean.v")

Result:
{
  "total_admits": 0,
  "filled": 0,
  "unfilled": 0,
  "results": [],
  "modified_script": "<original file contents unchanged>"
}
```

## 10. Language-Specific Notes (Python)

- Use `asyncio` for session lifecycle and search invocation.
- Admit location: use regex scanning with comment exclusion (track `(*` / `*)` nesting depth).
- Script assembly: use string slicing with byte-offset replacements applied in reverse order.
- Package location: `src/poule/search/fill_admits.py`.
- Entry point: `async def fill_admits(session_manager, search_engine, file_path, timeout_per_admit, max_depth, max_breadth) -> FillAdmitsResult`.
- Result types: `dataclasses` for FillAdmitsResult, AdmitResult, AdmitLocation.
