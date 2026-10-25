"""The `phy` command. Only parses arguments and calls plain functions."""

import re
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Annotated

import httpx
import structlog
import typer

import phy
from phy import filter as filter_stage
from phy import init as phy_init
from phy import log as phy_log
from phy import verify as verify_stage
from phy import watch as watch_stage
from phy.arxiv import ArxivUnavailable, OaiError
from phy.card import export_schemas
from phy.config import SCHEMAS, ConfigError, resolve_paths
from phy.ctx import Ctx
from phy.llm import ApiError, AuthError
from phy.locks import phy_lock
from phy.prompts import PromptError
from phy.read import stage as read_stage
from phy.read.flatten import NoMainFile
from phy.read.source import UnknownSourceFormat

log = structlog.get_logger()

ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")
WATCH_ERRORS = (ConfigError, ArxivUnavailable, OaiError, httpx.HTTPError)
FILTER_ERRORS = (ConfigError, AuthError, PromptError, filter_stage.UnknownPaper)
READ_ERRORS = (
    ConfigError,
    AuthError,
    ApiError,
    PromptError,
    ArxivUnavailable,
    OaiError,
    httpx.HTTPError,
    UnknownSourceFormat,
    tarfile.TarError,
    NoMainFile,
)
VERIFY_ERRORS = (ConfigError, verify_stage.NoCard)

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Physics Agent Platform.")
schema_app = typer.Typer(no_args_is_help=True, help="The Card JSON Schemas.")
app.add_typer(schema_app, name="schema")


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


def _arxiv_id(value: str | None) -> str | None:
    if value is not None and not ARXIV_ID.fullmatch(value):
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
    force: Annotated[
        bool, typer.Option("--force", help="Replace the Card if this Paper version has one.")
    ] = False,
) -> None:
    """Read one Paper: fetch and flatten its latest version, and write a draft Card."""
    paths = resolve_paths()
    with phy_lock(paths):
        try:
            outcome = read_stage.run(Ctx.load(paths), paper, dry_run=dry_run, force=force)
        except READ_ERRORS as e:
            log.error("read.failed", error=str(e))
            raise typer.Exit(1) from None
    match outcome:
        case read_stage.Prepared():
            typer.echo(f"{outcome.flattened}")
            typer.echo(f"{outcome.chars:,} chars, {outcome.tokens:,} tokens")
        case read_stage.Carded():
            typer.echo(
                f"card {outcome.card_id} (draft) for {paper}v{outcome.version},"
                f" ${outcome.cost_usd:.4f}"
            )
        case read_stage.AlreadyCarded():
            typer.echo(
                f"{paper}v{outcome.version} already has card {outcome.card_id};"
                " pass --force to replace it"
            )


@app.command()
def verify(
    paper: Annotated[
        str | None,
        typer.Option("--paper", callback=_arxiv_id, help="Verify only this Paper's latest Card."),
    ] = None,
    force: Annotated[
        bool, typer.Option("--force", help="Re-verify the --paper Card if already verified.")
    ] = False,
) -> None:
    """Check every draft Card's quotes against its flattened text and set Support."""
    if force and paper is None:
        raise typer.BadParameter("--force needs --paper")
    paths = resolve_paths()
    with phy_lock(paths):
        try:
            outcome = verify_stage.run(Ctx.load(paths), paper, force=force)
        except VERIFY_ERRORS as e:
            log.error("verify.failed", error=str(e))
            raise typer.Exit(1) from None
    match outcome:
        case verify_stage.AlreadyVerified():
            typer.echo(
                f"card {outcome.card_id} for {paper}v{outcome.version} is already verified;"
                " pass --force to re-verify it"
            )
        case verify_stage.Ran():
            typer.echo(f"{len(outcome.verified)} verified, {len(outcome.failed)} failed")
            if outcome.failed:
                raise typer.Exit(1)


@app.command()
def watch(
    since: Annotated[
        datetime | None,
        typer.Option(
            "--since",
            formats=["%Y-%m-%d"],
            help="Harvest from this day (YYYY-MM-DD); the mark never moves backwards.",
        ),
    ] = None,
    reset: Annotated[
        bool,
        typer.Option(
            "--reset", help="Clear the mark first, so the run backfills watch.backfill_days."
        ),
    ] = False,
) -> None:
    """Harvest every configured set since the high-water mark."""
    if since and reset:
        raise typer.BadParameter("--since and --reset cannot be combined")
    paths = resolve_paths()
    with phy_lock(paths):
        try:
            mark = watch_stage.run(Ctx.load(paths), since=since and since.date(), reset=reset)
        except WATCH_ERRORS as e:
            log.error("watch.failed", error=str(e))
            raise typer.Exit(1) from None
    typer.echo(f"mark: {mark.isoformat() if mark else 'none'}")


@app.command("filter")
def filter_(
    paper: Annotated[
        str | None,
        typer.Option(
            "--paper", callback=_arxiv_id, help="Screen only this Paper (its latest version)."
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", help="With --paper: replace its screening if it has one."),
    ] = False,
) -> None:
    """Screen every unscreened Paper version: the code pre-filter, then one Filter call per
    Candidate."""
    if force and paper is None:
        raise typer.BadParameter("--force needs --paper")
    paths = resolve_paths()
    with phy_lock(paths):
        try:
            screened = filter_stage.run(Ctx.load(paths), paper=paper, force=force)
        except FILTER_ERRORS as e:
            log.error("filter.failed", error=str(e))
            raise typer.Exit(1) from None
    typer.echo(
        f"{screened.candidates} candidates, {screened.screened_in} screened in,"
        f" {screened.prefilter_fails} pre-filter fail{'s' * (screened.prefilter_fails != 1)}"
        f", {screened.failed} failed calls"
    )
    if screened.failed:
        raise typer.Exit(1)


@schema_app.command("export")
def schema_export(
    directory: Annotated[Path, typer.Option("--dir", help="Where to write the schemas.")] = SCHEMAS,
) -> None:
    """Write the CardDraft and Card JSON Schemas (commit them, so schema changes show in diffs)."""
    for path in export_schemas(directory):
        typer.echo(str(path))
