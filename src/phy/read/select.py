"""Read's selection (SPEC §7.3): which Paper versions get Carded today.

`plan()` is the rule, a pure function: every Candidate at or over `read.always_threshold`;
then Stale re-cards, then the highest-scoring others, up to the day's quota; never more than
`read.weekly_ceiling` in the ISO week. The day's quota is `read.daily_quota` plus what earlier
days of the same ISO week left unused, carried forward day by day (a day over its quota leaves
nothing, never a debt). Every Card Read this week counts, `read --paper` ones included.

`select()` feeds it from the database and applies the weekly spend guardrail first.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import structlog

from phy import db
from phy.ctx import Ctx

log = structlog.get_logger()

Reason = Literal["always", "recard", "quota"]


@dataclass(frozen=True)
class Candidate:
    arxiv_id: str
    version: int
    best_score: float | None


@dataclass(frozen=True)
class Pick:
    arxiv_id: str
    version: int
    best_score: float | None
    reason: Reason


def week_start(day: date) -> date:
    """The Monday of `day`'s ISO week."""
    return day - timedelta(days=day.weekday())


def quota_left(used: dict[date, int], today: date, daily_quota: int) -> int:
    day, carry = week_start(today), 0
    while day < today:
        carry = max(0, daily_quota + carry - used.get(day, 0))
        day += timedelta(days=1)
    return max(0, daily_quota + carry - used.get(today, 0))


def plan(
    candidates: list[Candidate],
    recards: list[Candidate],
    used: dict[date, int],
    today: date,
    *,
    daily_quota: int,
    always_threshold: float,
    weekly_ceiling: int,
) -> list[Pick]:
    """`candidates` are Screened-in Paper versions without a Card, `recards` the latest versions
    of Papers whose Stale Card is to be re-Carded, and `used` the Cards Read per day."""
    by_score = sorted(candidates, key=lambda x: (-(x.best_score or 0), x.arxiv_id))
    always = [x for x in by_score if (x.best_score or 0) >= always_threshold]
    taken = {x.arxiv_id for x in always}
    recard = [x for x in recards if x.arxiv_id not in taken]
    taken |= {x.arxiv_id for x in recard}
    others = [x for x in by_score if x.arxiv_id not in taken]
    room = max(0, quota_left(used, today, daily_quota) - len(always))
    picks = [_pick(x, "always") for x in always] + [
        _pick(x, reason)
        for x, reason in ([(x, "recard") for x in recard] + [(x, "quota") for x in others])[:room]
    ]
    this_week = sum(n for day, n in used.items() if week_start(day) == week_start(today))
    return picks[: max(0, weekly_ceiling - this_week)]


def select(ctx: Ctx, today: date | None = None) -> list[Pick]:
    """Today's picks, best first, or none once the ISO week's spend reaches
    `budget.weekly_usd`. Days are UTC dates, as `runs.started_at` is."""
    config = ctx.config.read
    today = today or datetime.now(UTC).date()
    monday = week_start(today)
    spent = db.spend_since(ctx.db, monday)
    if spent >= ctx.config.budget.weekly_usd:
        log.warning("read.budget_reached", spent_usd=round(spent, 2))
        return []
    recards = []
    if config.recard_stale != "never":
        relevant_only = config.recard_stale == "relevant_only"
        recards = [Candidate(**r) for r in db.stale_cards(ctx.db, relevant_only=relevant_only)]
    return plan(
        [Candidate(**row) for row in db.uncarded_screened_in(ctx.db)],
        recards,
        {
            date.fromisoformat(row["day"]): row["cards"]
            for row in db.cards_read_since(ctx.db, monday)
        },
        today,
        daily_quota=config.daily_quota,
        always_threshold=config.always_threshold,
        weekly_ceiling=config.weekly_ceiling,
    )


def _pick(x: Candidate, reason: Reason) -> Pick:
    return Pick(arxiv_id=x.arxiv_id, version=x.version, best_score=x.best_score, reason=reason)
