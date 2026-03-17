Generate a complete, buildable Coq/Rocq project skeleton: directory structure, build system configuration, CI workflow, opam metadata, boilerplate source modules, and README. This command creates files and directories — it writes to the filesystem.

## Step 1: Collect project parameters

Ask the user for the following parameters. Accept whatever the user provides up front and only prompt for what is missing. Always confirm the final parameter set before generating anything.

**Required:**
- **Project name** — a valid Coq/opam identifier (lowercase, hyphens allowed, no spaces). If the user gives an invalid name, suggest a corrected version.

**Optional (with defaults):**
- **Build system** — `dune` (default) or `coq_makefile`. Recommend Dune for new projects.
- **Coq/Rocq version** — minimum version to support (default: `8.19`). Accept Rocq version numbers as well.
- **Logical path prefix** — the namespace for the project's theories (default: capitalize the project name, e.g., `my-lib` becomes `MyLib`).
- **Dependencies** — list of opam package dependencies (e.g., `coq-mathcomp-ssreflect`, `coq-equations`). Default: none.
- **License** — SPDX identifier (default: `MIT`).
- **Author name and email** — for opam metadata (default: prompt or use git config if available).
- **CI** — whether to generate GitHub Actions CI (default: yes).
- **Multi-library** — whether the project contains multiple coq.theory libraries (default: no, single library).

If the user provides all parameters in one message (e.g., "scaffold a project called my-proofs using dune with mathcomp"), skip the interactive prompts and proceed directly.

## Step 2: Resolve author information

If the user did not provide author name and email, attempt to read them from git config using Bash:

```
git config user.name
git config user.email
```

If both are available, use them. If not, ask the user.

## Step 3: Create directory structure

Create the project root directory and subdirectories. Use Bash with `mkdir -p` for all directories in a single call.

**For Dune projects:**
```
<project-name>/
  theories/          # Coq source files
  test/              # Test files
```

**For coq_makefile projects:**
```
<project-name>/
  theories/          # Coq source files
  test/              # Test files
```

If the user requested multi-library, create one subdirectory per library under `theories/`.

## Step 4: Generate build files

### Dune build system

Use Write to create each file.

**`dune-project`** in the project root:
- `(lang dune 3.0)` or higher as appropriate for the Coq version
- `(using coq 0.8)` or the appropriate Coq language version for Dune
- `(name <project-name>)`

**`theories/dune`**:
- A `(coq.theory ...)` stanza with:
  - `(name <LogicalPath>)`
  - `(theories ...)` listing any dependency logical names (e.g., `Mathcomp.ssreflect` for coq-mathcomp-ssreflect). Use `vernacular_query` with `Locate Library` on dependency module names if you need to verify the correct logical path for a dependency.

**`test/dune`**:
- A `(coq.theory ...)` stanza with:
  - `(name <LogicalPath>Test)` or `(name Test)`
  - `(theories <LogicalPath>)` to depend on the main library

For multi-library projects, generate a separate `dune` file in each library subdirectory with appropriate inter-library dependency declarations.

### coq_makefile build system

**`_CoqProject`** in the project root:
- `-Q theories <LogicalPath>`
- `-Q test <LogicalPath>Test` or `-Q test Test`
- List all `.v` files (initially just the boilerplate files)

**`Makefile`** in the project root:
- Standard `coq_makefile`-based Makefile that reads `_CoqProject`:
  ```makefile
  COQMAKEFILE := $(COQBIN)coq_makefile -f _CoqProject -o CoqMakefile

  all: CoqMakefile
  	$(MAKE) -f CoqMakefile

  CoqMakefile: _CoqProject
  	$(COQMAKEFILE)

  clean: CoqMakefile
  	$(MAKE) -f CoqMakefile clean
  	rm -f CoqMakefile CoqMakefile.conf

  .PHONY: all clean
  ```

## Step 5: Generate .opam file

Use Write to create `<project-name>.opam` in the project root with:

```
opam-version: "2.0"
name: "<project-name>"
version: "dev"
synopsis: "A Coq/Rocq project"
maintainer: "<author-email>"
authors: ["<author-name>"]
license: "<license>"
homepage: ""
bug-reports: ""
depends: [
  "ocaml"
  "coq" {>= "<coq-version>"}
  <each dependency with appropriate version constraints>
]
build: [
  <dune or make build instructions as appropriate>
]
install: [
  <dune or make install instructions as appropriate>
]
```

For Dune projects, use:
```
build: [["dune" "build" "-p" name "-j" jobs]]
install: [["dune" "install" "-p" name]]
```

For coq_makefile projects, use:
```
build: [make "-j" "%{jobs}%"]
install: [make "install"]
```

## Step 6: Generate .gitignore

Use Write to create `.gitignore` in the project root covering Coq build artifacts:

```
# Coq build artifacts
*.vo
*.vo[sk]
*.vio
*.vos
*.vok
*.glob
*.aux
.*.aux
*.d
*.a
*.o
*.cmi
*.cmo
*.cmx
*.cmxs
*.native
*.byte

# Dune
_build/
*.install

# coq_makefile
CoqMakefile
CoqMakefile.conf
.coqdeps.d

# Editors
*~
\#*\#
.#*
*.swp

# OS
.DS_Store
Thumbs.db
```

## Step 7: Generate GitHub Actions CI

If the user requested CI (the default), use Write to create `.github/workflows/build.yml`:

```yaml
name: Build

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        coq_version: ['<coq-version>']
    steps:
      - uses: actions/checkout@v4
      - uses: coq-community/docker-coq-action@v1
        with:
          coq_version: ${{ matrix.coq_version }}
          ocaml_version: default
          custom_script: |
            startGroup "Install dependencies"
            <opam install commands for each dependency>
            endGroup
            startGroup "Build"
            <dune build or make, as appropriate>
            endGroup
```

For Dune projects, the build command is `dune build`. For coq_makefile projects, it is `make -j$(nproc)`.

If dependencies were specified, include `opam install <dep1> <dep2> ...` in the Install dependencies step. If no dependencies, omit that group.

## Step 8: Generate boilerplate source modules

Use Write to create the following files:

**`theories/<LogicalPath>.v`** (root module matching the logical path name):
```coq
(** * <LogicalPath>

    Root module for the <project-name> project. *)

<import statements for each declared dependency, e.g.:>
(* From Mathcomp Require Import ssreflect. *)

(** Main definitions and results go here. *)
```

Use `vernacular_query` with `Check` or `Locate` to verify that the import paths for any declared dependencies are correct. If a dependency's import path cannot be verified (e.g., the dependency is not installed locally), use the conventional import path and leave a comment noting it should be verified.

**`test/Test.v`** (a minimal test file):
```coq
(** * Tests for <LogicalPath> *)

From <LogicalPath> Require Import <LogicalPath>.

(** Sanity check: the root module imports successfully. *)
Example sanity : True.
Proof. exact I. Qed.
```

## Step 9: Verify the project builds

Use Bash to attempt building the project:

For Dune projects:
```
cd <project-path> && dune build 2>&1
```

For coq_makefile projects:
```
cd <project-path> && make 2>&1
```

If the build succeeds, proceed to Step 10.

If the build fails, read the error output carefully and fix the issue. Common problems:
- Incorrect logical path in imports — fix the `From ... Require Import` statement
- Missing dependency declarations in dune files — add the dependency
- Syntax issues in dune-project — check the Dune language version

After fixing, retry the build. If the build still fails after two fix attempts, report the failure with the error output and explain what manual steps may be needed (e.g., installing missing dependencies).

## Step 10: Report what was created

Produce a summary listing:

1. Every file and directory created, as a tree
2. The build system chosen and the command to build (`dune build` or `make`)
3. Whether the build succeeded or failed (and what to fix if it failed)
4. The logical path for imports: `From <LogicalPath> Require Import ...`
5. Next steps the developer should take (e.g., "Add your theories to `theories/`, write your proofs, and run `dune build` to check them")

Keep the summary concise. Do not repeat file contents — the developer can read the files.

## Edge cases

- **Project directory already exists:** If a directory with the project name already exists at the target location, warn the user and ask whether to overwrite, merge, or abort. Never silently overwrite existing files.
- **Invalid project name:** If the project name contains characters invalid for opam packages or Coq logical paths, suggest a corrected name and confirm with the user before proceeding.
- **Unknown dependencies:** If a dependency name does not follow the `coq-*` opam naming convention, ask the user to confirm the exact opam package name.
- **Coq not installed:** If the build verification step fails because `coqc` or `dune` is not found, report this clearly and note that the generated files are still valid — they just need the toolchain installed to build.
- **Custom target directory:** If the user specifies a target directory (e.g., "scaffold in ~/projects/"), create the project there instead of the current working directory.
