"""The `phy` command. Only parses arguments and calls plain functions."""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

import structlog
import typer

import phy
from phy import daily as daily_stage
from phy import filter as filter_stage
from phy import flags as phy_flags
from phy import init as phy_init
from phy import llm
from phy import log as phy_log
from phy import schedule as phy_schedule
from phy import status as phy_status
from phy import verify as verify_stage
from phy import watch as watch_stage
from phy.card import export_schemas
from phy.config import SCHEMAS, ConfigError, load_config, resolve_paths
from phy.ctx import Ctx
from phy.locks import phy_lock
from phy.read import stage as read_stage
from phy.release import ReleaseError

log = structlog.get_logger()

ARXIV_ID = re.compile(r"\d{4}\.\d{4,5}")

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Physics Agent Platform.")
schema_app = typer.Typer(no_args_is_help=True, help="The Card JSON Schemas.")
app.add_typer(schema_app, name="schema")
schedule_app = typer.Typer(
    no_args_is_help=True, help="The launchd job that runs `phy daily` from the installed Release."
)
app.add_typer(schedule_app, name="schedule")


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
    except (ConfigError, llm.AuthError) as e:
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
        str | None,
        typer.Option(
            "--paper",
            callback=_arxiv_id,
            help="arXiv id (no version); the latest is read, bypassing selection.",
        ),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Stop after flattened.txt; print size and tokens.")
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Replace the Card if this Paper version has one.")
    ] = False,
) -> None:
    """Read today's selection (within quota and budget), or one Paper with --paper: fetch and
    flatten its latest version, and write a draft Card."""
    if (dry_run or force) and paper is None:
        raise typer.BadParameter("--dry-run and --force need --paper")
    paths = resolve_paths()
    with phy_lock(paths):
        try:
            ctx = Ctx.load(paths)
            if paper is None:
                selected = read_stage.run_selected(ctx)
            else:
                outcome = read_stage.run(ctx, paper, dry_run=dry_run, force=force)
        except read_stage.ERRORS as e:
            log.error("read.failed", error=str(e))
            raise typer.Exit(1) from None
    if paper is None:
        typer.echo(f"{len(selected.carded)} carded, {len(selected.failed)} failed")
        for failure in selected.failed:
            typer.echo(f"failed: {failure}")
        if selected.failed:
            raise typer.Exit(1)
        return
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
def daily() -> None:
    """Watch, Filter, Read and Verify in order. A failed Stage is logged and the later ones
    still run; the exit code is non-zero only for a crash."""
    paths = resolve_paths()
    with phy_lock(paths):
        try:
            ctx = Ctx.load(paths)
        except ConfigError as e:
            log.error("daily.failed", error=str(e))
            raise typer.Exit(1) from None
        ran = daily_stage.run(ctx)
    typer.echo(f"failed stages: {', '.join(ran.failed)}" if ran.failed else "all stages ok")
    if ran.crashed:
        raise typer.Exit(1)


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
        except verify_stage.ERRORS as e:
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
        except watch_stage.ERRORS as e:
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
        except filter_stage.ERRORS as e:
            log.error("filter.failed", error=str(e))
            raise typer.Exit(1) from None
    typer.echo(
        f"{screened.candidates} candidates, {screened.screened_in} screened in,"
        f" {screened.prefilter_fails} pre-filter fail{'s' * (screened.prefilter_fails != 1)}"
        f", {screened.failed} failed calls"
    )
    if screened.failed:
        raise typer.Exit(1)


@app.command()
def status() -> None:
    """High-water mark, 7-day funnel, the ISO week's spend, failures not retried, Release."""
    try:
        report = phy_status.status(resolve_paths())
    except ConfigError as e:
        log.error("status.failed", error=str(e))
        raise typer.Exit(1) from None
    typer.echo(phy_status.render(report))


def _days(value: str) -> timedelta:
    if not (m := re.fullmatch(r"(\d+)d", value)):
        raise typer.BadParameter(f"{value!r} is not a number of days like 30d")
    return timedelta(days=int(m.group(1)))


@app.command()
def flags(
    since: Annotated[
        timedelta,
        typer.Option("--since", parser=_days, help="How far back, in days (e.g. 30d)."),
    ] = "30d",
) -> None:
    """Flags grouped by field and kind, as input for Meta-work."""
    try:
        flagged = phy_flags.since(resolve_paths(), since)
    except ConfigError as e:
        log.error("flags.failed", error=str(e))
        raise typer.Exit(1) from None
    typer.echo(phy_flags.render(flagged, since))


@app.command()
def ui() -> None:
    """Serve the review UI on 127.0.0.1 (`ui.port`). Never takes phy.lock."""
    import uvicorn

    from phy.ui.app import create_app

    paths = resolve_paths()
    try:
        port = load_config(paths).ui.port
        web = create_app(paths)
    except ConfigError as e:
        log.error("ui.failed", error=str(e))
        raise typer.Exit(1) from None
    uvicorn.run(web, host="127.0.0.1", port=port)


@schema_app.command("export")
def schema_export(
    directory: Annotated[Path, typer.Option("--dir", help="Where to write the schemas.")] = SCHEMAS,
) -> None:
    """Write the CardDraft and Card JSON Schemas (commit them, so schema changes show in diffs)."""
    for path in export_schemas(directory):
        typer.echo(str(path))


@schedule_app.command("install")
def schedule_install() -> None:
    """Check out the newest Release at $PHY_HOME/app and load the 06:00 launchd job."""
    paths = resolve_paths()
    with phy_lock(paths), _schedule_errors("install"):
        tag = phy_schedule.install(paths)
    typer.echo(f"installed {tag}; {phy_schedule.LABEL} runs at 06:00 and at login")


@schedule_app.command("status")
def schedule_status() -> None:
    """Whether the job is loaded, the installed Release, and the last run."""
    with _schedule_errors("status"):
        s = phy_schedule.status(resolve_paths())
    typer.echo(phy_schedule.render(s))


@schedule_app.command("update")
def schedule_update() -> None:
    """Install the newest Release, once no run holds phy.lock. Refuses a downgrade."""
    paths = resolve_paths()
    with phy_lock(paths), _schedule_errors("update"):
        updated = phy_schedule.update(paths)
        typer.echo(phy_schedule.render_update(updated, paths))


@schedule_app.command("uninstall")
def schedule_uninstall() -> None:
    """Unload the job; remove its plist and $PHY_HOME/app. Data and config stay."""
    paths = resolve_paths()
    with phy_lock(paths), _schedule_errors("uninstall"):
        phy_schedule.uninstall(paths)
    typer.echo("uninstalled")


@contextmanager
def _schedule_errors(command: str) -> Iterator[None]:
    try:
        yield
    except ReleaseError as e:
        log.error(f"schedule.{command}_failed", error=str(e))
        raise typer.Exit(1) from None
