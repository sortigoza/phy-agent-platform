"""The Read Stage: fetch a Paper version's source, flatten it, and make one model call that
returns a draft Card.

`run_selected()` is the Stage run: selection (`phy.read.select`), then one Read per pick, each
its own run (`<run_id>-<arxiv_id>v<version>`), so one Paper failing doesn't stop the others.
The Stage run gets a `runs` row of its own, as Filter's does.

`run()` reads one Paper (`read --paper`). For a Paper not yet in `papers`, it calls `GetRecord`
and upserts it exactly as Watch would, then takes the latest version. It bypasses Filter and
writes no `screenings` row. A Paper version that already has a Card is left alone unless `force`
is set. A Read that fails before its model call still leaves a failed `runs` row.
"""

import hashlib
import shutil
import tarfile
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import get_args

import httpx
import structlog

from phy import db, llm
from phy.arxiv import Arxiv, ArxivUnavailable, OaiError
from phy.card import SCHEMA_VERSION
from phy.config import ConfigError
from phy.ctx import Ctx
from phy.log import log_failure
from phy.prompts import PromptError
from phy.read.flatten import NoMainFile, flatten, pdf_text
from phy.read.select import Reason, select
from phy.read.source import SourceFormat, UnknownSourceFormat, detect, unpack
from phy.tracer import Run

log = structlog.get_logger()

# What a Read fails with, logged without a traceback; anything else is a bug.
ERRORS = (
    ConfigError,
    llm.AuthError,
    llm.ApiError,
    PromptError,
    ArxivUnavailable,
    OaiError,
    httpx.HTTPError,
    UnknownSourceFormat,
    tarfile.TarError,
    NoMainFile,
)


@dataclass
class Prepared:
    arxiv_id: str
    version: int
    flattened: Path
    chars: int
    tokens: int


@dataclass
class Carded:
    arxiv_id: str
    version: int
    card_id: int
    cost_usd: float


@dataclass
class AlreadyCarded:
    arxiv_id: str
    version: int
    card_id: int


@dataclass
class Selected:
    carded: list[Carded] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # "<arxiv_id>v<n>: <error>"


def run_selected(ctx: Ctx, today: date | None = None) -> Selected:
    """Select today's Paper versions and Read each one."""
    with structlog.contextvars.bound_contextvars(run_id=ctx.run_id, stage="read"):
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            picks = select(ctx, today)
        except Exception as e:
            db.record_run(ctx.db, ctx.run_id, "read", "failed", started_at, error=str(e))
            raise
        db.record_run(ctx.db, ctx.run_id, "read", "ok", started_at)
        selected = Selected()
        for pick in picks:
            paper_ctx = replace(ctx, run_id=f"{ctx.run_id}-{pick.arxiv_id}v{pick.version}")
            try:
                outcome = run(paper_ctx, pick.arxiv_id)
            except Exception as e:
                with structlog.contextvars.bound_contextvars(
                    run_id=paper_ctx.run_id, arxiv_id=pick.arxiv_id, version=pick.version
                ):
                    log_failure(log, "read.paper_failed", e, ERRORS)
                selected.failed.append(f"{pick.arxiv_id}v{pick.version}: {e}")
                continue
            if isinstance(outcome, Carded):
                selected.carded.append(outcome)
        log.info(
            "read.finished",
            **{reason: sum(p.reason == reason for p in picks) for reason in get_args(Reason)},
            carded=len(selected.carded),
            failed=len(selected.failed),
        )
    return selected


def run(
    ctx: Ctx, arxiv_id: str, *, dry_run: bool = False, force: bool = False
) -> Prepared | Carded | AlreadyCarded:
    """`dry_run` stops after `flattened.txt` and counts its tokens instead of calling Read."""
    started_at = datetime.now(UTC).isoformat(timespec="seconds")
    try:
        return _read(ctx, arxiv_id, dry_run=dry_run, force=force)
    except Exception as e:
        # A failed model call has its row from the Tracer already.
        if not dry_run and db.get_run(ctx.db, ctx.run_id) is None:
            db.record_run(ctx.db, ctx.run_id, "read", "failed", started_at, str(e), arxiv_id)
        raise


def _read(
    ctx: Ctx, arxiv_id: str, *, dry_run: bool, force: bool
) -> Prepared | Carded | AlreadyCarded:
    config = ctx.config.read
    stage_run = Run(
        id=ctx.run_id,
        stage="read",
        arxiv_id=arxiv_id,
        model=config.model,
        prompt_version=config.prompt_version,
    )
    with structlog.contextvars.bound_contextvars(
        run_id=ctx.run_id, stage="read", arxiv_id=arxiv_id
    ):
        with Arxiv(ctx.paths, ctx.config.arxiv) as arxiv:
            version = latest_version(ctx, arxiv, arxiv_id)
            with structlog.contextvars.bound_contextvars(version=version):
                existing = db.get_card(ctx.db, arxiv_id, version)
                if existing is not None and not force and not dry_run:
                    log.info("read.skipped", reason="card_exists", card_id=existing["id"])
                    return AlreadyCarded(arxiv_id=arxiv_id, version=version, card_id=existing["id"])
                _, text = prepare(ctx, arxiv, arxiv_id, version)
        path = ctx.paths.flattened(arxiv_id, version)
        if dry_run:
            tokens = llm.count_tokens(config.model, text)
            return Prepared(
                arxiv_id=arxiv_id, version=version, flattened=path, chars=len(text), tokens=tokens
            )
        with structlog.contextvars.bound_contextvars(version=version):
            authors = db.get_paper(ctx.db, arxiv_id)["authors"]
            draft = llm.read_card(ctx, stage_run, text, authors)
            card_id = db.write_draft_card(
                ctx.db,
                arxiv_id,
                version,
                draft.model_dump_json(),
                model=config.model,
                prompt_version=config.prompt_version,
                schema_version=SCHEMA_VERSION,
                run_id=ctx.run_id,
            )
            cost = db.get_run(ctx.db, ctx.run_id)["cost_usd"]
            log.info("read.card_written", card_id=card_id, replaced=existing is not None)
    return Carded(arxiv_id=arxiv_id, version=version, card_id=card_id, cost_usd=cost)


def latest_version(ctx: Ctx, arxiv: Arxiv, arxiv_id: str) -> int:
    """The Paper's latest version, registering the Paper from `GetRecord` if it is new."""
    paper = db.get_paper(ctx.db, arxiv_id)
    if paper is None:
        record = arxiv.get_record(arxiv_id)
        db.upsert_paper(ctx.db, record)
        log.debug("read.paper_registered", versions=len(record.versions))
        return record.latest_version
    return paper["latest_version"]


def prepare(ctx: Ctx, arxiv: Arxiv, arxiv_id: str, version: int) -> tuple[SourceFormat, str]:
    """Fetch (or reuse) a Paper version's source and write its `flattened.txt`; the source
    format and the flattened text."""
    data, fmt, fetched = _source(ctx, arxiv, arxiv_id, version)
    text = _flatten(ctx, arxiv_id, version, data, fmt)
    ctx.paths.flattened(arxiv_id, version).write_text(text)
    log.debug("read.flattened", chars=len(text), format=fmt, fetched=fetched)
    return fmt, text


def _source(
    ctx: Ctx, arxiv: Arxiv, arxiv_id: str, version: int
) -> tuple[bytes, SourceFormat, bool]:
    """The raw download and whether it was fetched now; reused when it is on disk with the
    recorded checksum."""
    row = db.get_paper_version(ctx.db, arxiv_id, version)
    if row is not None and row["local_path"]:
        path = ctx.paths.home / row["local_path"]
        if path.is_file():
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() == row["sha256"]:
                log.debug("read.source_reused", bytes=len(data))
                return data, detect(data), False
            log.warning("read.source_checksum_mismatch")
    data = arxiv.get_source(arxiv_id, version)
    fmt = detect(data)
    path = ctx.paths.source_file(arxiv_id, version, fmt)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    db.record_source(
        ctx.db,
        arxiv_id,
        version,
        source_type="pdf" if fmt == "pdf" else "latex",
        local_path=str(path.relative_to(ctx.paths.home)),
        sha256=hashlib.sha256(data).hexdigest(),
    )
    log.debug("read.source_fetched", bytes=len(data), format=fmt)
    return data, fmt, True


def _flatten(ctx: Ctx, arxiv_id: str, version: int, data: bytes, fmt: SourceFormat) -> str:
    if fmt == "pdf":
        return pdf_text(ctx.paths.source_file(arxiv_id, version, fmt))
    tree = ctx.paths.source_tree(arxiv_id, version)
    shutil.rmtree(tree, ignore_errors=True)
    unpack(data, fmt, tree)
    return flatten(tree)
