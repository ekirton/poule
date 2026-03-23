"""CLI entry point for ``python -m poule.extraction``."""

import logging
import sys
from pathlib import Path

import click

from Poule.extraction.pipeline import run_extraction


@click.group(invoke_without_command=True)
@click.option(
    "--target",
    default=None,
    help=(
        'Library targets separated by "+". '
        "Built-in targets: stdlib, mathcomp. "
        "A filesystem path is also accepted."
    ),
)
@click.option(
    "--db",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to the output SQLite index database.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable debug logging for extraction (shows raw About output).",
)
@click.option(
    "--progress",
    is_flag=True,
    default=False,
    help="Print progress messages to stderr during extraction.",
)
@click.option(
    "--max-files",
    default=None,
    type=int,
    help="Randomly sample at most N .vo files from the discovered set.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    target: str | None,
    db: Path | None,
    verbose: bool,
    progress: bool,
    max_files: int | None,
) -> None:
    """Extract and index Coq libraries into a SQLite database."""
    # Backward compatibility: `python -m Poule.extraction --target X --db Y`
    # invokes the build directly without a subcommand.
    if ctx.invoked_subcommand is not None:
        return

    if target is None or db is None:
        click.echo(ctx.get_help())
        return

    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(message)s")
        logging.getLogger("poule.extraction").setLevel(logging.DEBUG)

    targets = [t.strip() for t in target.split("+") if t.strip()]

    def _progress(msg: str) -> None:
        click.echo(msg, err=True)

    try:
        report = run_extraction(
            targets=targets,
            db_path=db,
            progress_callback=_progress if progress else None,
            max_files=max_files,
        )
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(
        f"Done — indexed {report['declarations_indexed']} declarations "
        f"(Coq {report['coq_version']})"
    )


@cli.command("import-deps")
@click.option(
    "--deps",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the JSON Lines dependency graph file.",
)
@click.option(
    "--db",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Path to the existing index database.",
)
def import_deps(deps: Path, db: Path) -> None:
    """Import premise-based dependency edges into an existing index."""
    from Poule.extraction.dependency_graph import import_dependencies

    try:
        inserted = import_dependencies(deps, db)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    click.echo(f"Done — imported {inserted} dependency edges")


if __name__ == "__main__":
    cli()
