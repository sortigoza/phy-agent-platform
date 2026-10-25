"""The `phy` command. Only parses arguments and calls plain functions."""

import re
import tarfile
from typing import Annotated

import httpx
import structlog
import typer

import phy
from phy import init as phy_init
from phy import log as phy_log
from phy.arxiv import ArxivUnavailable, OaiError
from phy.config import ConfigError, resolve_paths
from phy.ctx import Ctx
from phy.llm import ApiError, AuthError
from phy.locks import phy_lock
from phy.read import stage as read_stage
from phy.read.flatten import NoMainFile
from phy.read.source import UnknownSourceFormat

log = structlog.get_logger()

ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")
READ_ERRORS = (
    ConfigError,
    AuthError,
    ApiError,
    ArxivUnavailable,
    OaiError,
    httpx.HTTPError,
    UnknownSourceFormat,
    tarfile.TarError,
    NoMainFile,
)

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


def _arxiv_id(value: str) -> str:
    if not ARXIV_ID.fullmatch(value):
        raise typer.BadParameter(f"{value!r} is not a new-style arXiv id like 1904.12072")
    return value


@app.command()
def read(
    paper: Annotated[
        str,
        typer.Option(
            "--paper", callback=_arxiv_id, help="arXiv id (no version); the latest is read."
        ),
    ],
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Stop after flattened.txt; print size and tokens.")
    ] = False,
) -> None:
    """Fetch one Paper's source and flatten it (the model call is not built yet: use --dry-run)."""
    if not dry_run:
        log.error("read.failed", error="the Read call is not built yet; use --dry-run")
        raise typer.Exit(1)
    paths = resolve_paths()
    with phy_lock(paths):
        try:
            prepared = read_stage.run(Ctx.load(paths), paper, dry_run=True)
        except READ_ERRORS as e:
            log.error("read.failed", error=str(e))
            raise typer.Exit(1) from None
    typer.echo(f"{prepared.flattened}")
    typer.echo(f"{prepared.chars:,} chars, {prepared.tokens:,} tokens")
