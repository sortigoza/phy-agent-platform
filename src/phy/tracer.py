"""The Tracer: the full record of every model call, kept outside the logs.

`record(run, request, response, error)` is the whole interface. `LocalTracer` appends one JSON
line per call to `$PHY_HOME/runs/<run_id>.jsonl` and folds the call into the run's `runs` row.
A Langfuse Tracer can be added later without touching any Stage.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from phy import db
from phy.config import Paths


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class Run:
    """One Stage execution, as the `runs` row describes it."""

    id: str
    stage: str
    arxiv_id: str | None
    model: str | None
    prompt_version: str | None
    started_at: str = field(default_factory=_now)


@dataclass
class Response:
    """What came back from one call: the raw response body and what it cost."""

    body: dict
    cost_usd: float
    duration_ms: int


class Tracer(Protocol):
    def record(
        self, run: Run, request: dict, response: Response | None, error: str | None
    ) -> None: ...


class LocalTracer:
    def __init__(self, paths: Paths, conn: sqlite3.Connection):
        self.paths = paths
        self.conn = conn

    def record(self, run: Run, request: dict, response: Response | None, error: str | None) -> None:
        ended_at = _now()
        path = self.paths.runs / f"{run.id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "run_id": run.id,
            "stage": run.stage,
            "arxiv_id": run.arxiv_id,
            "at": ended_at,
            "request": request,
            "response": response.body if response else None,
            "error": error,
            "cost_usd": response.cost_usd if response else 0.0,
            "duration_ms": response.duration_ms if response else None,
        }
        with path.open("a") as f:
            f.write(json.dumps(line) + "\n")
        usage = (response.body.get("usage") or {}) if response else {}
        db.record_run_call(
            self.conn,
            run_id=run.id,
            stage=run.stage,
            arxiv_id=run.arxiv_id,
            model=run.model,
            prompt_version=run.prompt_version,
            ok=error is None,
            error=error,
            tokens_in=usage.get("input_tokens") or 0,
            tokens_out=usage.get("output_tokens") or 0,
            cache_read_tokens=usage.get("cache_read_input_tokens") or 0,
            cache_write_tokens=usage.get("cache_creation_input_tokens") or 0,
            cost_usd=response.cost_usd if response else 0.0,
            started_at=run.started_at,
            ended_at=ended_at,
            log_path=str(path.relative_to(self.paths.home)),
        )
