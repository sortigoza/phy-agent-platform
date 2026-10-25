"""The `phy` command. Only parses arguments and calls plain functions."""

from typing import Annotated

import structlog
import typer

import phy
from phy import init as phy_init
from phy import log as phy_log
from phy.config import ConfigError, resolve_paths
from phy.llm import AuthError

log = structlog.get_logger()

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Physics Agent Platform.")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(phy.version())
        raise typer.Exit()


@app.callback()
def main(
    verbose: Annotated[bool, typer.Option("-v", "--verbose", help="Log DEBUG events.")] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_print_version, is_eager=True, help="Print the version."
        ),
    ] = False,
) -> None:
    phy_log.configure(resolve_paths(), verbose=verbose)
    # `version` is reserved for the Paper version, bound next to `arxiv_id`.
    structlog.contextvars.bind_contextvars(code_version=phy.version())


@app.command()
def init() -> None:
    """Create $PHY_HOME (config, questions, golden/, CHANGELOG.md, git repo, db) and check auth."""
    paths = resolve_paths()
    try:
        report = phy_init.run(paths)
    except (ConfigError, AuthError) as e:
        log.error("init.failed", error=str(e))
        raise typer.Exit(1) from None
    typer.echo(f"$PHY_HOME: {paths.home}")
    if report.created:
        typer.echo("created: " + ", ".join(report.created))
    else:
        typer.echo("nothing to create; existing files left as they are")
    if report.git_initialized:
        typer.echo("ran git init (phy never commits; commit your config edits yourself)")
    typer.echo(f"auth ok: {report.credential_source}")
