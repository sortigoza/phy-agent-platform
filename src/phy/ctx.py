"""What every Stage function `run(ctx, ...)` receives."""

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

from phy import db
from phy.config import Config, Paths, Questions, load_config, load_questions
from phy.tracer import LocalTracer, Tracer


@dataclass
class Ctx:
    paths: Paths
    config: Config
    questions: Questions
    db: sqlite3.Connection
    run_id: str
    tracer: Tracer

    @classmethod
    def load(cls, paths: Paths) -> "Ctx":
        """Validate config and questions first, so invalid config fails before any work."""
        config = load_config(paths)
        questions = load_questions(paths)
        conn = db.connect(paths.db)
        return cls(
            paths=paths,
            config=config,
            questions=questions,
            db=conn,
            run_id=new_run_id(),
            tracer=LocalTracer(paths, conn),
        )


def new_run_id() -> str:
    return f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{secrets.token_hex(3)}"
