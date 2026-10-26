"""The Golden set (SPEC §10): `golden/manifest.yaml`, the frozen sources and the Reference cards.

The manifest is instance config, validated like `config.toml`. `save()` rewrites it whole, so
any comment the Reader added is replaced by the standard header.

`add()` pins a Paper's latest version, freezes its source download and `flattened.txt` into
`golden_sources/<id>v<n>/`, and drafts a Placeholder Reference card with one Read call and
Verify, outside `cards`: the call is a `golden` run, so its cost counts against the budget but
not as a Card. `check()` compares every frozen source with its pinned sha256. phy never commits.
"""

import hashlib
import shlex
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Literal, get_args

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from phy import db, llm
from phy.arxiv import Arxiv
from phy.config import Paths, load_yaml
from phy.ctx import Ctx
from phy.read.source import SourceFormat
from phy.read.stage import ERRORS as READ_ERRORS
from phy.read.stage import latest_version, prepare
from phy.tracer import Run
from phy.verify import Source, verify_card

log = structlog.get_logger()

HEADER = "# Golden set (QUICK_START §7). Any change bumps version.\n"

Split = Literal["dev", "held_out"]
Status = Literal["placeholder", "trusted"]
Reason = Literal["seed", "review_mistake", "out_of_scope_probe", "awkward_source"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Entry(_Strict):
    """One Golden Paper, pinned to the version whose source is frozen in `golden_sources/`."""

    arxiv_id: str
    version: int
    sha256: str  # of the frozen source download
    split: Split
    status: Status
    reason: Reason
    expect_in_scope: bool
    added_at: date
    corrected_by: str | None  # who corrected the Reference card field by field
    corrected_at: date | None

    @model_validator(mode="after")
    def _trusted_is_corrected(self):
        if self.status == "trusted" and (self.corrected_by is None or self.corrected_at is None):
            raise ValueError("a trusted entry needs corrected_by and corrected_at")
        return self


class Manifest(_Strict):
    version: int
    papers: list[Entry]

    @model_validator(mode="after")
    def _one_entry_per_paper(self):
        ids = [p.arxiv_id for p in self.papers]
        if len(ids) != len(set(ids)):
            raise ValueError("each Paper appears once")
        return self


def load(paths: Paths) -> Manifest:
    return load_yaml(paths.golden_manifest, Manifest)


def save(paths: Paths, manifest: Manifest) -> None:
    body = yaml.safe_dump(manifest.model_dump(), sort_keys=False, allow_unicode=True)
    paths.golden_manifest.write_text(HEADER + body)


# M0 drafts at most 4 Placeholder Reference cards, all Dev (SPEC §10).
PLACEHOLDER_CAP = 4


class Refused(Exception):
    """`golden add` would break the manifest's rules; nothing was fetched or called."""


# What `golden add` fails with, logged without a traceback.
ERRORS = (Refused, *READ_ERRORS)


@dataclass
class Added:
    entry: Entry
    manifest_version: int
    cost_usd: float


def add(
    ctx: Ctx,
    arxiv_id: str,
    *,
    split: Split = "dev",
    reason: Reason = "seed",
    expect_in_scope: bool = True,
) -> Added:
    manifest = load(ctx.paths)
    _refuse(manifest, arxiv_id, split)
    with structlog.contextvars.bound_contextvars(
        run_id=ctx.run_id, stage="golden", arxiv_id=arxiv_id
    ):
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            entry = _add(ctx, arxiv_id, split, reason, expect_in_scope)
        except Exception as e:
            # A failed model call has its row from the Tracer already.
            if db.get_run(ctx.db, ctx.run_id) is None:
                db.record_run(ctx.db, ctx.run_id, "golden", "failed", started_at, str(e), arxiv_id)
            raise
        bumped = Manifest(version=manifest.version + 1, papers=[*manifest.papers, entry])
        save(ctx.paths, bumped)
        log.info("golden.added", version=entry.version, manifest_version=bumped.version)
    return Added(
        entry=entry,
        manifest_version=bumped.version,
        cost_usd=db.get_run(ctx.db, ctx.run_id)["cost_usd"],
    )


def _refuse(manifest: Manifest, arxiv_id: str, split: Split) -> None:
    if split == "held_out":
        raise Refused("M0 has only Dev; --split held_out comes with M1")
    if any(p.arxiv_id == arxiv_id for p in manifest.papers):
        raise Refused(f"{arxiv_id} is already in the Golden set")
    placeholders = sum(p.split == "dev" and p.status == "placeholder" for p in manifest.papers)
    if placeholders >= PLACEHOLDER_CAP:
        raise Refused(
            f"the Golden set already has {placeholders} Dev Placeholders, M0's cap;"
            " promote one to Trusted first"
        )


def _add(
    ctx: Ctx,
    arxiv_id: str,
    split: Split,
    reason: Reason,
    expect_in_scope: bool,
) -> Entry:
    paths, config = ctx.paths, ctx.config.read
    with Arxiv(paths, ctx.config.arxiv) as arxiv:
        version = latest_version(ctx, arxiv, arxiv_id)
        with structlog.contextvars.bound_contextvars(version=version):
            fmt, text = prepare(ctx, arxiv, arxiv_id, version)
    row = db.get_paper_version(ctx.db, arxiv_id, version)
    run = Run(
        id=ctx.run_id,
        stage="golden",
        arxiv_id=arxiv_id,
        model=config.model,
        prompt_version=config.prompt_version,
    )
    authors = db.get_paper(ctx.db, arxiv_id)["authors"]
    draft = llm.read_card(ctx, run, text, authors)
    verified = verify_card(draft, Source(text, row["source_type"]))

    # A frozen folder with no manifest entry is left by an add that failed after copying.
    frozen = paths.golden_source(arxiv_id, version)
    shutil.rmtree(frozen, ignore_errors=True)
    frozen.mkdir(parents=True)
    source = paths.golden_source_file(arxiv_id, version, fmt)
    shutil.copyfile(paths.source_file(arxiv_id, version, fmt), source)
    shutil.copyfile(paths.flattened(arxiv_id, version), paths.golden_flattened(arxiv_id, version))
    reference = paths.reference_card(arxiv_id)
    reference.parent.mkdir(parents=True, exist_ok=True)
    reference.write_text(verified.card.model_dump_json(indent=2) + "\n")
    return Entry(
        arxiv_id=arxiv_id,
        version=version,
        sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        split=split,
        status="placeholder",
        reason=reason,
        expect_in_scope=expect_in_scope,
        added_at=datetime.now(UTC).date(),
        corrected_by=None,
        corrected_at=None,
    )


def check(paths: Paths) -> list[str]:
    """Every frozen source that is missing or no longer matches its pinned sha256, as
    "<arxiv_id>v<n>: <problem>"; empty when the Golden set's inputs are intact."""
    problems = []
    for entry in load(paths).papers:
        name = f"{entry.arxiv_id}v{entry.version}"
        candidates = (
            paths.golden_source_file(entry.arxiv_id, entry.version, fmt)
            for fmt in get_args(SourceFormat)
        )
        source = next((path for path in candidates if path.is_file()), None)
        if source is None:
            problems.append(f"{name}: frozen source missing")
            continue
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != entry.sha256:
            problems.append(
                f"{name}: {source.name} sha256 is {actual[:12]}…, the manifest pins"
                f" {entry.sha256[:12]}…"
            )
    return problems


def commit_hint(paths: Paths, entry: Entry) -> str:
    """The `git` command the Reader may run; phy never commits."""
    files = [paths.golden_manifest, paths.reference_card(entry.arxiv_id)]
    staged = " ".join(str(f.relative_to(paths.home)) for f in files)
    home = shlex.quote(str(paths.home))
    return (
        f"git -C {home} add {staged} && git -C {home} commit -m"
        f" 'Golden: add {entry.arxiv_id}v{entry.version} ({entry.split} {entry.status})'"
    )
