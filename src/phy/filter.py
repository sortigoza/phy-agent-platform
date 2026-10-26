"""The Filter Stage (SPEC §7.2): screen every unscreened Paper version.

The pre-filter runs in code on the title and abstract, in the most permissive mode of the
Paper's sets. A Paper that passes (or whose mode is `none`) is a Candidate and gets one Filter
call. Every Paper version screened gets a `screenings` row, a pre-filter fail included.

Each call is its own run (`<run_id>-<arxiv_id>v<version>`, one `runs` row and one trace file),
so the run viewer shows one Paper per run as it does for Read. The Stage run itself gets a
`runs` row too, which pre-filter fails point at. A failed call leaves its Paper version
unscreened, so the next run tries it again; the other Candidates go ahead.
"""

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import structlog

from phy import db, llm, prompts
from phy.config import ConfigError, Prefilter, Questions
from phy.ctx import Ctx
from phy.tracer import Run

log = structlog.get_logger()

PrefilterResult = Literal["pass", "fail", "skipped"]
# Most permissive first.
MODES: list[Prefilter] = ["none", "keywords", "keywords+physics"]


def prefilter(
    title: str, abstract: str, sets: list[str], modes: dict[str, Prefilter], questions: Questions
) -> PrefilterResult:
    """`keywords` passes when some question's keyword matches and none of that question's
    negative keywords do, and no global negative keyword matches; `keywords+physics` also needs
    a physics term. A term matches case-insensitively at a word start, so plurals still match.
    Sets missing from `modes` are ignored; a Paper left with none gets the strictest mode."""
    mode = min((modes[s] for s in sets if s in modes), key=MODES.index, default=MODES[-1])
    if mode == "none":
        return "skipped"
    text = f"{title}\n{abstract}"
    if _any_match(questions.negative_keywords, text):
        return "fail"
    if not any(
        _any_match(q.keywords, text) and not _any_match(q.negative_keywords, text)
        for q in questions.questions
    ):
        return "fail"
    if mode == "keywords+physics" and not _any_match(questions.physics_terms, text):
        return "fail"
    return "pass"


def _any_match(terms: list[str], text: str) -> bool:
    return any(
        re.search(r"\b" + r"\s+".join(map(re.escape, term.split())), text, re.IGNORECASE)
        for term in terms
    )


def decide(scores: dict[str, dict], threshold: float) -> tuple[float, bool]:
    """A Candidate's best score across the questions, and whether it is Screened in."""
    best = max(item["score"] for item in scores.values())
    return best, best >= threshold


class UnknownPaper(Exception):
    pass


# What a Filter run fails with, logged without a traceback; a failed call fails only its Paper.
ERRORS = (ConfigError, llm.AuthError, prompts.PromptError, UnknownPaper)


@dataclass
class Screened:
    candidates: int = 0
    screened_in: int = 0
    prefilter_fails: int = 0
    failed: int = 0


def run(ctx: Ctx, *, paper: str | None = None, force: bool = False) -> Screened:
    """Screen every unscreened Paper version, or only `paper`'s latest version; `force`
    replaces its screening if it has one."""
    with structlog.contextvars.bound_contextvars(run_id=ctx.run_id, stage="filter"):
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            todo = _todo(ctx, paper, force)
            log.info("filter.started", paper_versions=len(todo))
            screened, fails = _screen(ctx, todo)
        except Exception as e:
            db.record_run(ctx.db, ctx.run_id, "filter", "failed", started_at, error=str(e))
            raise
        db.record_run(ctx.db, ctx.run_id, "filter", "ok", started_at)
        # Written after the Stage's own `runs` row, which they reference.
        for row in fails:
            db.write_screening(
                ctx.db,
                arxiv_id=row["arxiv_id"],
                version=row["version"],
                prefilter="fail",
                scores_json=None,
                best_score=None,
                screened_in=False,
                model=None,
                prompt_version=None,
                run_id=ctx.run_id,
            )
        log.info("filter.finished", **vars(screened))
    return screened


def _todo(ctx: Ctx, paper: str | None, force: bool) -> list:
    if paper is None:
        return db.unscreened(ctx.db)
    row = db.get_paper(ctx.db, paper)
    if row is None:
        raise UnknownPaper(f"{paper} is not in the database; run `phy watch` or `phy read` first")
    version = row["latest_version"]
    if db.get_screening(ctx.db, paper, version) is not None and not force:
        log.info("filter.skipped", reason="screened", arxiv_id=paper, version=version)
        return []
    return [{**dict(row), "version": version}]


def _screen(ctx: Ctx, todo: list) -> tuple[Screened, list]:
    config = ctx.config.filter
    screened, fails = Screened(), []
    for row in todo:
        arxiv_id, version = row["arxiv_id"], row["version"]
        result = prefilter(
            row["title"],
            row["abstract"],
            row["sets"].split(),
            ctx.config.watch.prefilter,
            ctx.questions,
        )
        if result == "fail":
            screened.prefilter_fails += 1
            fails.append(row)
            continue
        screened.candidates += 1
        call = Run(
            id=f"{ctx.run_id}-{arxiv_id}v{version}",
            stage="filter",
            arxiv_id=arxiv_id,
            model=config.model,
            prompt_version=config.prompt_version,
        )
        with structlog.contextvars.bound_contextvars(arxiv_id=arxiv_id, version=version):
            try:
                scores = llm.screen(ctx, call, row["title"], row["categories"], row["abstract"])
            except llm.ApiError as e:
                log.error("filter.call_failed", error=str(e))
                screened.failed += 1
                continue
            best, screened_in = decide(scores, config.threshold)
            if screened_in:
                screened.screened_in += 1
            db.write_screening(
                ctx.db,
                arxiv_id=arxiv_id,
                version=version,
                prefilter=result,
                scores_json=json.dumps(scores),
                best_score=best,
                screened_in=screened_in,
                model=config.model,
                prompt_version=config.prompt_version,
                run_id=call.id,
            )
            log.debug("filter.screened", prefilter=result, best_score=best)
    return screened, fails
