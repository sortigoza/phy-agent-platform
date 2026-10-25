"""The Read Stage. This slice goes as far as `flattened.txt`; the model call comes next.

For a Paper not yet in `papers`, Read calls `GetRecord` and upserts it exactly as Watch would,
then takes the latest version. It bypasses Filter and writes no `screenings` row.
"""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

import structlog

from phy import db, llm
from phy.arxiv import Arxiv
from phy.ctx import Ctx
from phy.read.flatten import flatten, pdf_text
from phy.read.source import SourceFormat, detect, unpack

log = structlog.get_logger()


@dataclass
class Prepared:
    arxiv_id: str
    version: int
    flattened: Path
    chars: int
    tokens: int


def run(ctx: Ctx, arxiv_id: str, *, dry_run: bool) -> Prepared:
    if not dry_run:
        raise NotImplementedError("the Read call is not built yet; use --dry-run")
    with structlog.contextvars.bound_contextvars(
        run_id=ctx.run_id, stage="read", arxiv_id=arxiv_id
    ):
        with Arxiv(ctx.paths, ctx.config.arxiv) as arxiv:
            version = _latest_version(ctx, arxiv, arxiv_id)
            with structlog.contextvars.bound_contextvars(version=version):
                data, fmt, fetched = _source(ctx, arxiv, arxiv_id, version)
                text = _flatten(ctx, arxiv_id, version, data, fmt)
                path = ctx.paths.flattened(arxiv_id, version)
                path.write_text(text)
                log.info("read.flattened", chars=len(text), format=fmt, fetched=fetched)
        tokens = llm.count_tokens(ctx.config.read.model, text)
    return Prepared(
        arxiv_id=arxiv_id, version=version, flattened=path, chars=len(text), tokens=tokens
    )


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
