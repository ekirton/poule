# Nightly Re-index Automation

Scheduled detection of new upstream Coq library versions, re-extraction of changed libraries, and publication of updated index assets.

**Architecture**: [nightly-reindex.md](../doc/architecture/nightly-reindex.md)
**Feature**: [modular-index-distribution.md](../doc/features/modular-index-distribution.md) (Developer Automation)
**Stories**: [modular-index-distribution.md](../doc/requirements/stories/modular-index-distribution.md) (Epic 6)

---

> **Blast radius — changes required to existing specifications:**
>
> **specification/prebuilt-distribution.md SS5 (Publish Script):** The publish script currently aborts when the release tag already exists (SS5 step 6). The nightly re-index script requires replacing existing releases with updated assets. The publish script must accept a `--replace` flag that, when present, deletes the existing release and its tag before creating a new one. Without `--replace`, the existing abort-on-duplicate behavior is preserved. See SS4.7 of this specification for the contract.

---

## 1. Purpose

Define two shell scripts that automate the nightly re-indexing cycle: an inner script (`scripts/nightly-reindex.sh`) that runs inside the container to detect version changes, re-extract changed libraries, and publish updated assets; and an outer script (`scripts/reindex-cron.sh`) that runs on the host to launch the container and propagate the result.

## 2. Scope

**In scope:**

- Version detection for the 6 supported libraries via `coqc` and `opam`
- Comparison of installed versions against the published manifest
- Selective re-extraction of changed libraries
- Carry-forward of unchanged library assets from the current release
- Publication of a replacement release via `scripts/publish-release.sh --replace`
- Host-side container launcher suitable for cron scheduling

**Out of scope:**

- Extraction pipeline internals (owned by specification/extraction.md)
- Publish script internals beyond the `--replace` flag (owned by specification/prebuilt-distribution.md)
- Index merging (owned by specification/prebuilt-distribution.md)
- Cron scheduling configuration (user-managed)
- Notification or alerting on failure

## 3. Definitions

| Term | Definition |
|------|-----------|
| Inner script | `scripts/nightly-reindex.sh`, runs inside the container |
| Outer script | `scripts/reindex-cron.sh`, runs on the host |
| Manifest | The `manifest.json` asset in the latest `index-v*` GitHub Release, containing per-library version and checksum metadata |
| Published version | The library version string recorded in the manifest for a given library |
| Installed version | The library version currently available in the container's Coq/opam environment |
| Workdir | A temporary directory (`workdir/`) created by the inner script for staging extraction outputs and downloaded assets |

## 4. Behavioral Requirements

### 4.1 Opam Package Mapping

The inner script shall map library identifiers to opam package names using this fixed table:

| Library identifier | Version source |
|-------------------|---------------|
| `stdlib` | `coqc --version` (parse version string) |
| `mathcomp` | `opam list coq-mathcomp-ssreflect --short --columns=version` |
| `stdpp` | `opam list coq-stdpp --short --columns=version` |
| `flocq` | `opam list coq-flocq --short --columns=version` |
| `coquelicot` | `opam list coq-coquelicot --short --columns=version` |
| `coqinterval` | `opam list coq-interval --short --columns=version` |

- REQUIRES: `coqc` and `opam` are on `PATH`. The 5 opam packages are installed.
- ENSURES: Each command returns a single version string. For `coqc --version`, the script extracts the numeric version (e.g., `8.19.2`) from the output line.
- MAINTAINS: The set of 6 library identifiers matches the supported libraries defined in `specification/prebuilt-distribution.md SS3`.

> **Given** `coqc --version` outputs `The Coq Proof Assistant, version 8.19.2`
> **When** the inner script detects the stdlib version
> **Then** it records `8.19.2` as the installed version for `stdlib`

> **Given** `opam list coq-mathcomp-ssreflect --short --columns=version` outputs `2.2.0`
> **When** the inner script detects the mathcomp version
> **Then** it records `2.2.0` as the installed version for `mathcomp`

### 4.2 Manifest Fetch

The inner script shall fetch the current manifest from the latest `index-v*` GitHub Release.

- REQUIRES: `gh` CLI is authenticated (via `GH_TOKEN` environment variable). Network access to the GitHub API.
- ENSURES: Downloads `manifest.json` from the latest release whose tag starts with `index-v`, using `gh release view --json tagName,assets`. Parses the manifest to extract the `libraries` object containing per-library `version` fields.
- On no existing release (first run): the script treats all 6 libraries as changed and proceeds with full extraction.
- On GitHub API failure: the script aborts with exit code 1.

> **Given** the latest release is tagged `index-v1-coq8.19` with a manifest listing `stdlib: 8.19.2, mathcomp: 2.2.0`
> **When** the inner script fetches the manifest
> **Then** it records the published versions for comparison

> **Given** no release with `index-v*` tag exists
> **When** the inner script fetches the manifest
> **Then** it treats all 6 libraries as changed

### 4.3 Version Comparison

The inner script shall compare installed versions against published versions for each of the 6 libraries.

- REQUIRES: Installed versions have been detected (SS4.1). Published versions have been fetched or the first-run fallback applies (SS4.2).
- ENSURES: A library is classified as "changed" when its installed version differs from its published version, or when no published version exists for that library. A library is classified as "unchanged" when its installed version exactly matches its published version.

> **Given** installed mathcomp version is `2.3.0` and published version is `2.2.0`
> **When** the inner script compares versions
> **Then** mathcomp is classified as changed

> **Given** installed stdlib version is `8.19.2` and published version is `8.19.2`
> **When** the inner script compares versions
> **Then** stdlib is classified as unchanged

### 4.4 Early Exit on No Changes

When no libraries are classified as changed, the inner script shall log `All indexes are current.` to stderr and exit with code 0. No extraction, download, or publication occurs.

> **Given** all 6 installed versions match the published versions
> **When** the inner script completes version comparison
> **Then** it prints `All indexes are current.` to stderr and exits 0

### 4.5 Extraction of Changed Libraries

For each library classified as changed, the inner script shall run extraction.

- REQUIRES: The library's compiled `.vo` files are installed in the container. `workdir/` directory exists (created by the script).
- ENSURES: Runs `python -m Poule.extraction --target <library> --db workdir/index-<library>.db --progress` for each changed library. On success, `workdir/index-<library>.db` contains the re-extracted index.
- On extraction failure for a single library: logs an error to stderr, skips that library, and carries forward the previous release asset (same as unchanged libraries per SS4.6). The library is reclassified as unchanged for the purposes of SS4.6.
- On extraction failure for all changed libraries: aborts with exit code 1. No publication occurs.

> **Given** mathcomp is classified as changed
> **When** the inner script runs extraction
> **Then** it executes `python -m Poule.extraction --target mathcomp --db workdir/index-mathcomp.db --progress`

> **Given** extraction fails for mathcomp but succeeds for flocq
> **When** the inner script handles the failure
> **Then** it logs the error, carries forward the previous `index-mathcomp.db`, and continues with flocq's new extraction

> **Given** extraction fails for all changed libraries
> **When** the inner script handles the failures
> **Then** it aborts with exit code 1 and does not publish

### 4.6 Carry-Forward of Unchanged Libraries

For each library classified as unchanged (or reclassified per SS4.5), the inner script shall download the existing asset from the current release.

- REQUIRES: The current release exists and contains the asset `index-<library>.db`.
- ENSURES: Downloads `index-<library>.db` from the current release into `workdir/` using `gh release download`.

> **Given** stdlib is unchanged and the current release contains `index-stdlib.db`
> **When** the inner script prepares assets
> **Then** it downloads `index-stdlib.db` from the release into `workdir/`

### 4.7 Publication

After extraction and carry-forward are complete, the inner script shall publish a replacement release.

- REQUIRES: `workdir/` contains `index-<library>.db` for all 6 libraries (either freshly extracted or carried forward). `scripts/publish-release.sh` is executable.
- ENSURES: Runs `scripts/publish-release.sh --replace workdir/index-*.db`. The `--replace` flag causes the publish script to delete any existing release with the same tag before creating the new one. On success, the release is published with all 6 per-library assets and a regenerated manifest.
- On `gh release create` failure: aborts with exit code 1.

**Contract for `--replace` flag on `publish-release.sh`:**

When `--replace` is passed, the publish script shall, after computing the release tag (existing step 5), check whether that tag already exists. If it does, the script shall delete the existing release and its tag via `gh release delete <tag> --yes` and `git push origin :refs/tags/<tag>`, then proceed to create the new release. If `--replace` is not passed, the existing abort-on-duplicate behavior (specification/prebuilt-distribution.md SS5 step 6) is preserved.

> **Given** the computed tag is `index-v1-coq8.19` and that release already exists
> **When** `publish-release.sh --replace` runs
> **Then** it deletes the existing release, deletes the tag, creates the new release with updated assets

> **Given** the computed tag is `index-v1-coq8.19` and no release with that tag exists
> **When** `publish-release.sh --replace` runs
> **Then** it creates the new release (delete step is a no-op)

### 4.8 Logging and Output

- REQUIRES: Nothing.
- ENSURES: The inner script writes progress messages to stderr, error messages to stderr, and a summary to stdout.
- MAINTAINS: The summary lists which libraries were checked, which were re-extracted, and the release tag.

Summary format (stdout):

```
Nightly re-index summary:
  Re-extracted: mathcomp 2.3.0, flocq 4.3.0
  Unchanged:    stdlib 8.19.2, stdpp 1.12.0, coquelicot 3.4.3, coqinterval 4.11.4
  Release:      index-v1-coq8.19
```

When no changes are detected, no summary is printed (SS4.4 applies instead).

### 4.9 Outer Script (reindex-cron.sh)

The outer script shall launch the inner script inside a container.

- REQUIRES: `docker` is on `PATH`. `GH_TOKEN` environment variable is set with `contents:write` scope.
- ENSURES: Executes the following steps in order:
  1. Pulls the latest dev image: `docker pull ghcr.io/ekirton/Poule:dev`
  2. Runs the inner script: `docker run --rm -e GH_TOKEN="$GH_TOKEN" ghcr.io/ekirton/Poule:dev /poule/scripts/nightly-reindex.sh`
  3. Exits with the same exit code as the `docker run` command.
- MAINTAINS: The outer script does not interpret or modify the inner script's output. stdout and stderr from the container are passed through to the caller.

> **Given** `GH_TOKEN` is set and the container image exists
> **When** the outer script runs
> **Then** it pulls the latest image, runs the inner script, and exits with the inner script's exit code

> **Given** `GH_TOKEN` is not set
> **When** the inner script attempts `gh` operations inside the container
> **Then** `gh` reports an authentication error and the inner script exits 1, which the outer script propagates

## 5. Error Specification

### nightly-reindex.sh (inner script)

| Condition | Category | Exit code | stderr message |
|-----------|----------|-----------|---------------|
| `GH_TOKEN` not set / `gh` auth failure | dependency error | 1 | `Error: GitHub authentication failed. Set GH_TOKEN with contents:write scope.` |
| GitHub API unreachable | dependency error | 1 | `Error: Failed to reach GitHub API.` |
| `coqc` not found | dependency error | 1 | `Error: coqc not found on PATH.` |
| `opam` not found | dependency error | 1 | `Error: opam not found on PATH.` |
| `opam list` fails for one library | dependency error | continues | `Warning: Could not detect version for <library>. Skipping.` |
| Extraction fails for one library | dependency error | continues | `Error: Extraction failed for <library>. Carrying forward previous asset.` |
| Extraction fails for all changed libraries | dependency error | 1 | `Error: All extractions failed. Aborting.` |
| `gh release download` fails for carry-forward | dependency error | 1 | `Error: Failed to download <asset> from release <tag>.` |
| `publish-release.sh` fails | dependency error | 1 | `Error: Release publication failed.` |

### reindex-cron.sh (outer script)

| Condition | Category | Exit code | stderr message |
|-----------|----------|-----------|---------------|
| `docker` not found | dependency error | 1 | `Error: docker not found on PATH.` |
| `GH_TOKEN` not set | input error | 1 | `Error: GH_TOKEN environment variable is not set.` |
| `docker pull` fails | dependency error | 1 | (docker's own error message) |
| `docker run` fails | dependency error | non-zero | (propagated from container) |

### publish-release.sh --replace (addition to existing spec)

| Condition | Category | Exit code | stderr message |
|-----------|----------|-----------|---------------|
| `gh release delete` fails | dependency error | 1 | `Error: Failed to delete existing release {tag}.` |
| Tag deletion fails | dependency error | 1 | `Error: Failed to delete tag {tag}.` |

## 6. Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Total runtime (no changes) | Under 30 seconds |
| Total runtime (full re-extraction, 6 libraries) | Under 45 minutes |
| Disk usage in workdir | Under 500 MB |
| External dependencies (inner script) | `gh`, `python`, `coqc`, `opam`, `bash` |
| External dependencies (outer script) | `docker`, `bash` |
| Idempotency | Running the inner script twice with no upstream changes produces no release changes on the second run |

## 7. Examples

### No changes detected

```
$ ./scripts/nightly-reindex.sh
Fetching manifest from latest release...               # stderr
Detecting installed versions...                         # stderr
  stdlib:       8.19.2 (published: 8.19.2)              # stderr
  mathcomp:     2.2.0  (published: 2.2.0)               # stderr
  stdpp:        1.12.0 (published: 1.12.0)              # stderr
  flocq:        4.2.1  (published: 4.2.1)               # stderr
  coquelicot:   3.4.3  (published: 3.4.3)               # stderr
  coqinterval:  4.11.4 (published: 4.11.4)              # stderr
All indexes are current.                                # stderr
```

### One library updated

```
$ ./scripts/nightly-reindex.sh
Fetching manifest from latest release...                # stderr
Detecting installed versions...                         # stderr
  stdlib:       8.19.2 (published: 8.19.2)              # stderr
  mathcomp:     2.3.0  (published: 2.2.0) *changed*     # stderr
  stdpp:        1.12.0 (published: 1.12.0)              # stderr
  flocq:        4.2.1  (published: 4.2.1)               # stderr
  coquelicot:   3.4.3  (published: 3.4.3)               # stderr
  coqinterval:  4.11.4 (published: 4.11.4)              # stderr
Extracting mathcomp...                                  # stderr
Downloading unchanged assets...                         # stderr
Publishing release...                                   # stderr
Nightly re-index summary:                               # stdout
  Re-extracted: mathcomp 2.3.0                          # stdout
  Unchanged:    stdlib 8.19.2, stdpp 1.12.0, flocq 4.2.1, coquelicot 3.4.3, coqinterval 4.11.4
  Release:      index-v1-coq8.19                        # stdout
```

### First run (no existing release)

```
$ ./scripts/nightly-reindex.sh
Fetching manifest from latest release...                # stderr
No existing release found. Treating all as changed.     # stderr
Detecting installed versions...                         # stderr
  stdlib:       8.19.2 (no published version)            # stderr
  mathcomp:     2.2.0  (no published version)            # stderr
  stdpp:        1.12.0 (no published version)            # stderr
  flocq:        4.2.1  (no published version)            # stderr
  coquelicot:   3.4.3  (no published version)            # stderr
  coqinterval:  4.11.4 (no published version)            # stderr
Extracting stdlib...                                    # stderr
Extracting mathcomp...                                  # stderr
Extracting stdpp...                                     # stderr
Extracting flocq...                                     # stderr
Extracting coquelicot...                                # stderr
Extracting coqinterval...                               # stderr
Publishing release...                                   # stderr
Nightly re-index summary:                               # stdout
  Re-extracted: stdlib 8.19.2, mathcomp 2.2.0, stdpp 1.12.0, flocq 4.2.1, coquelicot 3.4.3, coqinterval 4.11.4
  Unchanged:    (none)                                  # stdout
  Release:      index-v1-coq8.19                        # stdout
```

### Host-side cron invocation

```
$ ./scripts/reindex-cron.sh
dev: Pulling from ekirton/Poule                         # stderr (docker pull)
Status: Image is up to date for ghcr.io/ekirton/Poule:dev
All indexes are current.                                # stderr (from container)
$ echo $?
0
```

## 8. Language-Specific Notes (Bash)

- Both scripts use `#!/usr/bin/env bash` with `set -euo pipefail`.
- The inner script creates `workdir/` via `mktemp -d` or a fixed path relative to the repository root, and cleans it up on exit via a `trap` handler.
- Version string parsing for `coqc --version` uses parameter expansion or `sed` to extract the numeric version.
- The inner script exits early (code 0) when no changes are detected, which is a success condition for cron.
- The outer script validates `GH_TOKEN` before invoking `docker run` to provide a clear error message rather than a cryptic container failure.
