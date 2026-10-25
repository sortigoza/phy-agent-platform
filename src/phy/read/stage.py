"""The Read Stage: fetch a Paper version's source, flatten it, and make one model call that
returns a draft Card.

For a Paper not yet in `papers`, Read calls `GetRecord` and upserts it exactly as Watch would,
then takes the latest version. It bypasses Filter and writes no `screenings` row. A Paper
version that already has a Card is left alone unless `force` is set.
"""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import structlog

from phy import db, llm
from phy.arxiv import Arxiv
from phy.card import SCHEMA_VERSION
from phy.ctx import Ctx
from phy.read.flatten import flatten, pdf_text
from phy.read.source import SourceFormat, detect, unpack
from phy.tracer import Run

log = structlog.get_logger()


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


def run(
    ctx: Ctx, arxiv_id: str, *, dry_run: bool = False, force: bool = False
) -> Prepared | Carded | AlreadyCarded:
    """`dry_run` stops after `flattened.txt` and counts its tokens instead of calling Read."""
    config = ctx.config.read
    tracked = Run(
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
            version = _latest_version(ctx, arxiv, arxiv_id)
            with structlog.contextvars.bound_contextvars(version=version):
                existing = db.get_card(ctx.db, arxiv_id, version)
                if existing is not None and not force and not dry_run:
                    log.info("read.skipped", reason="card_exists", card_id=existing["id"])
                    return AlreadyCarded(arxiv_id, version, existing["id"])
                data, fmt, fetched = _source(ctx, arxiv, arxiv_id, version)
                text = _flatten(ctx, arxiv_id, version, data, fmt)
                path = ctx.paths.flattened(arxiv_id, version)
                path.write_text(text)
                log.info("read.flattened", chars=len(text), format=fmt, fetched=fetched)
        if dry_run:
            tokens = llm.count_tokens(config.model, text)
            return Prepared(
                arxiv_id=arxiv_id, version=version, flattened=path, chars=len(text), tokens=tokens
            )
        with structlog.contextvars.bound_contextvars(version=version):
            authors = db.get_paper(ctx.db, arxiv_id)["authors"]
            draft = llm.read_card(ctx, tracked, text, authors)
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
    return Carded(arxiv_id, version, card_id, cost)


def _latest_version(ctx: Ctx, arxiv: Arxiv, arxiv_id: str) -> int:
    paper = db.get_paper(ctx.db, arxiv_id)
    if paper is None:
        record = arxiv.get_record(arxiv_id)
        db.upsert_paper(ctx.db, record)
        log.debug("read.paper_registered", versions=len(record.versions))
        return record.latest_version
    return paper["latest_version"]


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
