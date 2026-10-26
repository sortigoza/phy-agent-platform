"""`phy status`: the pipeline at a glance, from SQLite. Never takes `phy.lock`.

The funnel counts what happened in the last 7 days at each step, dated as the monitor page
dates it: a Paper version by its first OAI datestamp, a screening and a Card by the run that
wrote them, a Review by its own time. A failure is listed, however old, while no later `ok` run
of the same Stage (and Paper, for per-Paper runs) exists.
"""

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from phy import db
from phy.config import Paths, load_config
from phy.read.select import week_start
from phy.release import ReleaseStatus, release_status
from phy.watch import HWM, LAST_SUCCESS

WINDOW = timedelta(days=7)
FUNNEL_STEPS = [
    ("harvested", "harvested"),
    ("candidates", "candidates"),
    ("screened_in", "screened in"),
    ("carded", "carded"),
    ("verified", "verified"),
    ("reviewed", "reviewed"),
    ("relevant", "relevant"),
    ("deep_read", "deep read"),
]


@dataclass
class Status:
    mark: str | None
    last_success_at: str | None
    funnel: dict[str, int]
    week_start: str
    spent_usd: float
    weekly_usd: float
    failures: list[sqlite3.Row]
    release: ReleaseStatus


def status(paths: Paths, now: datetime | None = None) -> Status:
    """Raises ConfigError for invalid config, as every command does."""
    config = load_config(paths)
    now = now or datetime.now(UTC)
    monday = week_start(now.date())
    conn = db.connect(paths.db)
    try:
        return Status(
            mark=db.get_state(conn, HWM),
            last_success_at=db.get_state(conn, LAST_SUCCESS),
            funnel=db.funnel(conn, (now - WINDOW).isoformat(timespec="seconds")),
            week_start=monday.isoformat(),
            spent_usd=db.spend_since(conn, monday),
            weekly_usd=config.budget.weekly_usd,
            failures=db.unretried_failures(conn),
            release=release_status(paths),
        )
    finally:
        conn.close()


def render(s: Status) -> str:
    if s.mark is None and s.last_success_at is None:
        watch = "watch: no mark yet, never succeeded"
    else:
        last = (
            f"{datetime.fromisoformat(s.last_success_at).astimezone(UTC):%Y-%m-%d %H:%M} UTC"
            if s.last_success_at
            else "never"
        )
        watch = f"watch: mark {s.mark or 'none'}, last success {last}"
    funnel = ", ".join(f"{s.funnel[key]} {label}" for key, label in FUNNEL_STEPS)
    spend = f"spend (ISO week from {s.week_start}): ${s.spent_usd:.2f} of ${s.weekly_usd:.2f}"
    if s.spent_usd >= s.weekly_usd:
        spend += "; guardrail reached: Read selects nothing until Monday"
    if s.failures:
        failures = [f"failures not retried ({len(s.failures)}):"] + [
            "  " + " ".join(filter(None, [f["stage"], f["arxiv_id"], f["id"] + ":", f["error"]]))
            for f in s.failures
        ]
    else:
        failures = ["failures not retried: none"]
    return "\n".join([watch, f"funnel (7 days): {funnel}", spend, *failures, _release(s.release)])


def _release(r: ReleaseStatus) -> str:
    if r.installed is None:
        return "release: none installed"
    if r.update_available:
        return (
            f"release: {r.installed}; update available: {r.newest} ({len(r.commits)} commits),"
            " run `phy schedule update`"
        )
    return f"release: {r.installed} (newest)"
