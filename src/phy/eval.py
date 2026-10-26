"""`phy eval` (SPEC §10): Read, Verify and Filter on the frozen Golden sources, scored and
stored in `eval_runs`.

Every input is checked before any model call: each frozen source must match its pinned
sha256, the split must have Papers, and each Paper must be in `papers`, which holds Filter's
title and abstract and Read's authors. `prompt_versions` overrides the active prompt versions.

Each call is its own `eval` run (`<run_id>-<arxiv_id>v<n>-read` and `-filter`), traced as
usual, so eval spend counts against `budget.weekly_usd`. Eval Cards are stored whole in
`per_paper_json` and never in `cards`, so they don't count against `read.weekly_ceiling`. A
failed call fails the eval and stores no Scores, since Scores over part of the set aren't
comparable.
"""

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Literal

import structlog

from phy import db, golden, llm, prompts
from phy.config import ConfigError
from phy.ctx import Ctx
from phy.prompts import PromptError
from phy.tracer import Run
from phy.verify import Source, facts, verify_card

log = structlog.get_logger()

PromptStage = Literal["read", "filter"]


class Refused(Exception):
    """The eval's inputs are not usable; no model call was made."""


# What `phy eval` fails with, logged without a traceback.
ERRORS = (Refused, ConfigError, llm.AuthError, llm.ApiError, PromptError)


@dataclass
class Evaluated:
    run_id: str
    metrics: dict
    per_paper: list[dict]


@dataclass
class _Input:
    entry: golden.Entry
    paper: dict
    text: str
    source_type: Literal["latex", "pdf"]


def run(
    ctx: Ctx,
    *,
    prompt_versions: dict[PromptStage, str] | None = None,
    split: golden.Split = "dev",
) -> Evaluated:
    ctx = _with_prompts(ctx, prompt_versions or {})
    with structlog.contextvars.bound_contextvars(run_id=ctx.run_id, stage="eval"):
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            manifest = golden.load(ctx.paths)
            inputs = _inputs(ctx, manifest, split)
            log.info("eval.started", papers=len(inputs), golden_version=manifest.version)
            per_paper = [_score(ctx, i) for i in inputs]
        except Exception as e:
            db.record_run(ctx.db, ctx.run_id, "eval", "failed", started_at, error=str(e))
            raise
        db.record_run(ctx.db, ctx.run_id, "eval", "ok", started_at)
        metrics = _metrics(per_paper)
        config = ctx.config
        db.write_eval_run(
            ctx.db,
            run_id=ctx.run_id,
            golden_version=manifest.version,
            split=split,
            prompt_versions_json=json.dumps(
                {"read": config.read.prompt_version, "filter": config.filter.prompt_version}
            ),
            model=config.read.model,
            metrics_json=json.dumps(metrics),
            per_paper_json=json.dumps(per_paper),
        )
        log.info("eval.finished", **metrics)
    return Evaluated(run_id=ctx.run_id, metrics=metrics, per_paper=per_paper)


def _with_prompts(ctx: Ctx, overrides: dict[PromptStage, str]) -> Ctx:
    """`ctx` with each overridden Stage's `prompt_version` replaced, so the calls load it."""
    updates = {
        stage: getattr(ctx.config, stage).model_copy(update={"prompt_version": version})
        for stage, version in overrides.items()
    }
    return replace(ctx, config=ctx.config.model_copy(update=updates))


def _inputs(ctx: Ctx, manifest: golden.Manifest, split: golden.Split) -> list[_Input]:
    problems = golden.check(ctx.paths)
    if problems:
        raise Refused("frozen sources don't match the manifest: " + "; ".join(problems))
    entries = [e for e in manifest.papers if e.split == split]
    if not entries:
        raise Refused(f"the Golden set has no {split} Papers; add one with `phy golden add`")
    for stage in ["read", "filter"]:
        prompts.load(stage, getattr(ctx.config, stage).prompt_version)
    inputs = []
    for entry in entries:
        name = f"{entry.arxiv_id}v{entry.version}"
        paper = db.get_paper(ctx.db, entry.arxiv_id)
        if paper is None:
            raise Refused(f"{entry.arxiv_id} is not in the database, so Filter has no metadata")
        flattened = ctx.paths.golden_flattened(entry.arxiv_id, entry.version)
        if not flattened.is_file():
            raise Refused(f"{name}: frozen flattened.txt missing")
        source = golden.frozen_source(ctx.paths, entry)
        inputs.append(
            _Input(
                entry=entry,
                paper=dict(paper),
                text=flattened.read_text(),
                source_type="pdf" if source.name.endswith(".pdf") else "latex",
            )
        )
    return inputs


def _score(ctx: Ctx, i: _Input) -> dict:
    """One Paper's eval Card and Scores."""
    entry, paper = i.entry, i.paper
    name = f"{entry.arxiv_id}v{entry.version}"
    read, filter_ = ctx.config.read, ctx.config.filter
    with structlog.contextvars.bound_contextvars(arxiv_id=entry.arxiv_id, version=entry.version):
        read_run = Run(
            id=f"{ctx.run_id}-{name}-read",
            stage="eval",
            arxiv_id=entry.arxiv_id,
            model=read.model,
            prompt_version=read.prompt_version,
        )
        draft = llm.read_card(ctx, read_run, i.text, paper["authors"])
        verified = verify_card(draft, Source(i.text, i.source_type))
        filter_run = Run(
            id=f"{ctx.run_id}-{name}-filter",
            stage="eval",
            arxiv_id=entry.arxiv_id,
            model=filter_.model,
            prompt_version=filter_.prompt_version,
        )
        scores = llm.screen(ctx, filter_run, paper["title"], paper["categories"], paper["abstract"])
        quotes = [q for f in facts(verified.card) for q in f.evidence]
        found = sum(q.found for q in quotes)
        best = max(item["score"] for item in scores.values())
        screened_in = best >= filter_.threshold
        scored = {
            "arxiv_id": entry.arxiv_id,
            "version": entry.version,
            "quotes": len(quotes),
            "quotes_found": found,
            "grounding_rate": found / len(quotes) if quotes else None,
            "invented_numbers": [vars(n) for n in verified.invented_numbers],
            "filter": {
                "scores": scores,
                "best_score": best,
                "screened_in": screened_in,
                "expect_in_scope": entry.expect_in_scope,
                "correct": screened_in == entry.expect_in_scope,
            },
            "card": verified.card.model_dump(mode="json"),
        }
        log.debug(
            "eval.scored",
            grounding_rate=scored["grounding_rate"],
            invented_numbers=len(verified.invented_numbers),
            filter_correct=scored["filter"]["correct"],
        )
    return scored


def _metrics(per_paper: list[dict]) -> dict:
    """The overall Scores: grounding over every quote, invented numbers (any is a hard fail),
    and how many Filter decisions match the manifest."""
    quotes = sum(p["quotes"] for p in per_paper)
    found = sum(p["quotes_found"] for p in per_paper)
    invented = sum(len(p["invented_numbers"]) for p in per_paper)
    return {
        "grounding_rate": found / quotes if quotes else None,
        "quotes": quotes,
        "quotes_found": found,
        "invented_numbers": invented,
        "hard_fail": invented > 0,
        "filter_correct": sum(p["filter"]["correct"] for p in per_paper),
        "filter_total": len(per_paper),
    }


def render(evaluated: Evaluated) -> str:
    """The Scores per Paper, then overall, then the run id."""

    def grounding(s: dict) -> str:
        if s["grounding_rate"] is None:
            return "grounding n/a (0 quotes)"
        return f"grounding {s['grounding_rate']:.1%} ({s['quotes_found']}/{s['quotes']})"

    def scope(in_scope: bool) -> str:
        return "in" if in_scope else "out"

    lines = []
    for p in evaluated.per_paper:
        invented = ", ".join(n["number"] for n in p["invented_numbers"])
        f = p["filter"]
        lines.append(
            f"{p['arxiv_id']}v{p['version']}  {grounding(p)}"
            f"  invented numbers {len(p['invented_numbers'])}{f' ({invented})' * bool(invented)}"
            f"  Filter {scope(f['screened_in'])} (expected {scope(f['expect_in_scope'])})"
            f" {'ok' if f['correct'] else 'WRONG'}"
        )
    m = evaluated.metrics
    lines.append(
        f"overall  {grounding(m)}  invented numbers {m['invented_numbers']}"
        f"  Filter {m['filter_correct']}/{m['filter_total']} correct"
        + ("  hard fail: invented numbers" if m["hard_fail"] else "")
    )
    lines.append(f"eval run {evaluated.run_id}")
    return "\n".join(lines)
