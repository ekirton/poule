# Publishing Releases

Prebuilt search indexes and neural model checkpoints are distributed via two [GitHub Releases](https://github.com/ekirton/Poule/releases):

| Release tag | Contents |
|-------------|----------|
| `index-libraries` | 6 per-library `index-*.db` files + `manifest.json` |
| `index-merged` | Single merged `index.db` + `manifest.json` (+ optional ONNX model) |

The `index-merged` release is a **build-time dependency** of the Docker image. The Dockerfile downloads `index.db` during build and validates that library versions in the manifest match the installed opam packages. A version mismatch fails the build. Matching indexes must be published before merging Dockerfile changes that bump library versions.

## When to publish

Publish a new release when any of these change:
- Coq version (new stdlib declarations)
- Any supported library version (new library content)
- Index schema version (storage layer changes)
- Neural model (retrained or improved checkpoint)

## Prerequisites

- [`gh`](https://cli.github.com/) CLI, authenticated (`gh auth login`)
- `sqlite3` (reads version metadata from the index)
- `shasum` (computes checksums)

## Publishing

1. Check what upstream versions are available:

```bash
./scripts/check-latest.sh
```

2. Search the web for version incompatibilities between the libraries before choosing versions to bump.

3. Update pinned versions in `Dockerfile` (do not commit yet), exit the container, and run `poule-dev` to rebuild with the new versions.

4. Build per-library indexes:

```bash
./scripts/build-indexes.sh
```

5. Point the MCP server at the newly built index and restart it:

```bash
export POULE_MCP_DB=~/index.db
poule-mcp restart
```

6. **Decision gate.** Integration tests run automatically during the build, but verify the results yourself — check that proofs compile, indexes look correct, and nothing regressed. Decide whether to proceed with the version bump or roll back.

7. Publish releases (must precede the PR — the Docker build downloads the index from these releases):

```bash
./scripts/publish-indexes.sh
# Or include the neural model:
./scripts/publish-indexes.sh --model models/neural-premise-selector.onnx
```

8. Create a branch, commit the `Dockerfile` changes, push, and open a PR with auto-merge. The CI/CD pipeline will build a new container image with the updated index baked in.

## Release assets

**`index-libraries` release:**

| Asset | Description |
|-------|-------------|
| `index-stdlib.db` | Per-library index: Coq standard library |
| `index-mathcomp.db` | Per-library index: Mathematical Components |
| `index-stdpp.db` | Per-library index: std++ |
| `index-flocq.db` | Per-library index: Flocq |
| `index-coquelicot.db` | Per-library index: Coquelicot |
| `index-coqinterval.db` | Per-library index: CoqInterval |
| `manifest.json` | Version metadata and SHA-256 checksums |

**`index-merged` release:**

| Asset | Description |
|-------|-------------|
| `index.db` | Merged search index (all 6 libraries) |
| `manifest.json` | Version metadata, SHA-256, and library versions |
| `neural-premise-selector.onnx` | INT8 ONNX model (optional) |

The Dockerfile fetches `manifest.json` from `index-merged`, downloads `index.db`, verifies its SHA-256, and validates library versions against installed opam packages. See [`specification/prebuilt-distribution.md`](../specification/prebuilt-distribution.md) for the full protocol.
