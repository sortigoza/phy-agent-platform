"""`/monitor` (SPEC §9): the M0 Instruments, each one named SQL query over the §6 tables, with
its window, red rule, note and link; and the funnel of the last 7 days.

Screenings and Cards are dated by their run's `started_at`. A windowed query takes `:start` and
`:end` (ISO timestamps or dates, compared as text), so its sparkline is the same query run once
per day.
"""

import sqlite3
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode

from phy import db
from phy.config import Config
from phy.read.select import week_start
from phy.watch import HWM, LAST_SUCCESS

State = Literal["green", "red", "grey"]
QUESTIONS = {
    "running": "Is it running?",
    "funnel": "Is the funnel shaped right?",
    "right": "Is it right?",
    "useful": "Is it useful?",
    "affordable": "Is it affordable?",
}
WINDOW = timedelta(days=7)

QUERIES = {
    # The latest Mon–Fri on or before the last successful Watch, and the versions it first carried.
    "harvested": """
        WITH target AS (
          SELECT date(value, '-' || CASE strftime('%w', value) WHEN '0' THEN 2 WHEN '6' THEN 1
                                    ELSE 0 END || ' days') AS day
          FROM state WHERE key = :last_success)
        SELECT day, (SELECT count(*) FROM paper_versions WHERE first_seen_datestamp = day) AS value
        FROM target""",
    "harvested_bars": """
        SELECT count(*) AS value FROM paper_versions
        WHERE first_seen_datestamp >= :start AND first_seen_datestamp < :end""",
    # The mark moves to the run's responseDate, so its date is the day it last advanced. Mon–Fri
    # count as announcement days; arXiv holidays are ignored.
    "hwm_days": """
        WITH RECURSIVE mark AS (SELECT value FROM state WHERE key = :hwm),
        d(day) AS (SELECT date(value, '+1 day') FROM mark
                   UNION ALL SELECT date(day, '+1 day') FROM d WHERE day < :today)
        SELECT (SELECT value FROM mark) AS mark,
               (SELECT count(*) FROM d WHERE strftime('%w', day) BETWEEN '1' AND '5'
                AND day <= :today) AS value""",
    # Each Stage and Paper with a failed or aborted run in the window and no later ok run of
    # the same Stage and Paper. `skipped` runs (too long to Read) are not failures. A Paper with
    # 3 failed Reads is given up: selection no longer retries it.
    "failures": """
        SELECT f.stage, f.arxiv_id, group_concat(DISTINCT f.status) AS statuses,
               f.stage = 'read' AND (SELECT count(*) FROM runs x WHERE x.stage = 'read'
                 AND x.arxiv_id = f.arxiv_id AND x.status = 'failed'
                 AND x.started_at > coalesce((SELECT max(o.started_at) FROM runs o
                   WHERE o.stage = 'read' AND o.arxiv_id = f.arxiv_id AND o.status = 'ok'), ''))
                 >= 3 AS given_up
        FROM runs f
        WHERE f.status IN ('failed', 'aborted') AND f.started_at >= :start AND f.started_at < :end
          AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.stage = f.stage AND r.arxiv_id IS f.arxiv_id
                          AND r.status = 'ok' AND r.started_at > f.started_at)
        GROUP BY f.stage, f.arxiv_id ORDER BY f.stage, f.arxiv_id""",
    # A Candidate passed the pre-filter, or its set skips it.
    "candidates": """
        SELECT count(*) AS value,
               (SELECT min(started_at) FROM runs WHERE stage = 'filter') AS first_filter
        FROM screenings s JOIN runs r ON r.id = s.run_id
        WHERE s.prefilter IN ('pass', 'skipped') AND r.started_at >= :start
          AND r.started_at < :end""",
    # Unsupported fields over the fields that carry a Support, on the Cards Read in the window.
    "unsupported": """
        SELECT sum(c.unsupported_count) * 1.0 / nullif(sum(
                 (SELECT count(*) FROM json_tree(c.card_json) WHERE key = 'support')), 0) AS value,
               count(*) AS cards
        FROM cards c JOIN runs r ON r.id = c.run_id
        WHERE c.status != 'draft' AND r.started_at >= :start AND r.started_at < :end""",
    # The last 7 Golden eval runs, newest first: the tile shows the first, the bars all of them.
    "grounding": """
        SELECT id, created_at, json_extract(metrics_json, '$.grounding_rate') AS value
        FROM eval_runs ORDER BY created_at DESC, id DESC LIMIT 7""",
    # Cards Read in the window with an invented number, and the latest eval run's count.
    "invented": """
        WITH recent AS (SELECT c.* FROM cards c JOIN runs r ON r.id = c.run_id
                        WHERE c.status != 'draft' AND r.started_at >= :start
                          AND r.started_at < :end),
        latest AS (SELECT * FROM eval_runs ORDER BY created_at DESC, id DESC LIMIT 1)
        SELECT (SELECT count(*) FROM recent) AS cards,
               (SELECT count(*) FROM recent WHERE json_array_length(invented_numbers_json) > 0)
                 AS value,
               (SELECT max(id) FROM recent WHERE json_array_length(invented_numbers_json) > 0)
                 AS card_id,
               (SELECT json_extract(metrics_json, '$.invented_numbers') FROM latest) AS golden,
               (SELECT id FROM latest) AS eval_id""",
    # The last 7 Dev eval runs, newest first. `baseline_id` and `material_changes` are filled by
    # the run-to-run diff.
    "golden_diff": """
        SELECT id, baseline_id, material_changes AS value, accepted_at FROM eval_runs
        WHERE split = 'dev' ORDER BY created_at DESC, id DESC LIMIT 7""",
    # Yes and partly both count as relevant, as in the Stale re-card rule.
    "precision": """
        SELECT avg(relevance IN ('yes', 'partly')) AS value, count(*) AS reviews
        FROM reviews WHERE created_at >= :start AND created_at < :end""",
    # SQLite has no median: the middle row, or the mean of the two middle rows.
    "review_time": """
        WITH s AS (SELECT seconds_spent AS x, row_number() OVER (ORDER BY seconds_spent) AS i,
                          count(*) OVER () AS n
                   FROM reviews WHERE seconds_spent IS NOT NULL AND created_at >= :start
                     AND created_at < :end)
        SELECT avg(x) / 60.0 AS value, max(n) AS reviews FROM s
        WHERE i IN ((n + 1) / 2, (n + 2) / 2)""",
    # The median over the papers Carded in the window of every pipeline run tied to the paper,
    # whenever it ran, retries included; and the first Card's Read: the baseline is the same
    # median over the 7 days from it.
    "cost_per_card": """
        WITH carded AS (
          SELECT DISTINCT c.arxiv_id FROM cards c JOIN runs r ON r.id = c.run_id
          WHERE r.started_at >= :start AND r.started_at < :end),
        per AS (
          SELECT k.arxiv_id, sum(coalesce(r.cost_usd, 0)) AS x
          FROM carded k JOIN runs r ON r.arxiv_id = k.arxiv_id
          WHERE r.stage NOT IN ('golden', 'eval') GROUP BY k.arxiv_id),
        s AS (SELECT x, row_number() OVER (ORDER BY x) AS i, count(*) OVER () AS n FROM per)
        SELECT avg(x) AS value, max(n) AS papers,
               (SELECT min(r.started_at) FROM cards c JOIN runs r ON r.id = c.run_id)
                 AS first_card
        FROM s WHERE i IN ((n + 1) / 2, (n + 2) / 2)""",
    "spend_by_stage": """
        SELECT stage, sum(cost_usd) AS usd FROM runs
        WHERE started_at >= :start AND started_at < :end GROUP BY stage HAVING usd > 0
        ORDER BY usd DESC, stage""",
    "spend": """
        SELECT coalesce(sum(cost_usd), 0) AS value FROM runs
        WHERE started_at >= :start AND started_at < :end""",
    # Review time is the one Reader activity M0 records.
    "minutes_per_relevant": """
        SELECT sum(coalesce(seconds_spent, 0)) / 60.0 AS minutes,
               sum(relevance IN ('yes', 'partly')) AS relevant, count(*) AS reviews
        FROM reviews WHERE created_at >= :start AND created_at < :end""",
    "wasted_minutes": """
        SELECT sum(CASE relevance WHEN 'no' THEN coalesce(seconds_spent, 0) ELSE 0 END) / 60.0
                 AS value, count(*) AS reviews
        FROM reviews WHERE created_at >= :start AND created_at < :end""",
    # Shown on the funnel strip next to Carded, with no red rule.
    "skipped_too_long": """
        SELECT count(DISTINCT arxiv_id) AS value FROM runs
        WHERE stage = 'read' AND status = 'skipped' AND started_at >= :start
          AND started_at < :end""",
}
QUERIES["failures_bars"] = f"SELECT count(*) AS value FROM ({QUERIES['failures']})"
# Red rules the SPEC §9 table fixes; the rest are `alerts.*` and `budget.*` in config.toml.
HWM_DAYS = 2
GROUNDING_RATE = 0.98
PRECISION = 0.70
PRECISION_MIN_REVIEWS = 20
COST_MULTIPLE = 2
SPEND_FRACTION = 0.90
NO_EVAL = "no Golden eval run yet: run phy eval"


@dataclass(frozen=True)
class Bar:
    """One bar of a sparkline: a day, or for Golden tiles an eval run."""

    value: float
    weekend: bool = False


@dataclass(frozen=True)
class Tile:
    key: str
    name: str
    question: str  # a key of QUESTIONS
    state: State
    value: str  # as shown; "—" when there is nothing to show
    rule: str  # the red rule, as shown
    action: str  # what to do when it is red (SPEC §9 table)
    note: str = ""  # what the value covers
    why: str | None = None  # why the tile is grey
    link: str | None = None
    bars: tuple[Bar, ...] = ()

    @property
    def link_kind(self) -> Literal["eval", "card", "runs"] | None:
        """What `link` opens: a Golden eval run, a Card, or the run list."""
        if self.link is None:
            return None
        if self.link.startswith("/eval/"):
            return "eval"
        return "card" if self.link.startswith("/cards/") else "runs"


def instruments(conn: sqlite3.Connection, config: Config, now: datetime) -> list[Tile]:
    """Every M0 Instrument at `now` (UTC), in the SPEC §9 table's order."""
    m = _Measure(conn, config, now.astimezone(UTC))
    return [
        m.harvested(),
        m.hwm_days(),
        m.failures(),
        m.candidates(),
        m.unsupported(),
        m.grounding(),
        m.invented(),
        m.golden_diff(),
        m.precision(),
        m.review_time(),
        m.cost_per_card(),
        m.spend(),
        m.minutes_per_relevant(),
        m.wasted_minutes(),
    ]


FUNNEL_STEPS = {
    "harvested": "harvested",
    "candidates": "Candidates",
    "screened_in": "Screened in",
    "carded": "Carded",
    "verified": "verified",
    "reviewed": "reviewed",
    "relevant": "relevant",
    "deep_read": "deep read",
}


@dataclass(frozen=True)
class Step:
    key: str
    label: str
    count: int
    share: float | None  # of the step before; None for the first step or after a 0


@dataclass(frozen=True)
class Funnel:
    steps: list[Step]
    skipped_too_long: int  # Papers whose Read was skipped as too long


def funnel(conn: sqlite3.Connection, now: datetime) -> Funnel:
    """What happened at each step in the last 7 days: activity counts, not a cohort, so a step
    can exceed 100% of the one before (reviewing last week's Cards)."""
    now = now.astimezone(UTC)
    start = _iso(now - WINDOW)
    counts = db.funnel(conn, start)
    steps, before = [], None
    for key, label in FUNNEL_STEPS.items():
        steps.append(Step(key, label, counts[key], counts[key] / before if before else None))
        before = counts[key]
    skipped = _rows(conn, "skipped_too_long", start=start, end=_iso(now))[0]["value"]
    return Funnel(steps, skipped)


class _Measure:
    def __init__(self, conn: sqlite3.Connection, config: Config, now: datetime):
        self.conn, self.config, self.now = conn, config, now
        self.start = _iso(now - WINDOW)
        self.end = _iso(now)

    def q(self, name: str, **params) -> sqlite3.Row:
        return self.rows(name, **params)[0]

    def rows(self, name: str, **params) -> list[sqlite3.Row]:
        return _rows(self.conn, name, **params)

    def days(self, name: str, value=lambda row: row["value"]) -> tuple[Bar, ...]:
        """The query once per UTC day of the last 7, today last; weekend bars are grey."""
        today = self.now.date()
        out = []
        for k in range(6, -1, -1):
            day = today - timedelta(days=k)
            row = self.q(name, start=day.isoformat(), end=(day + timedelta(days=1)).isoformat())
            out.append(Bar(value(row) or 0, _weekend(day)))
        return tuple(out)

    def harvested(self) -> Tile:
        row = next(iter(self.rows("harvested", last_success=LAST_SUCCESS)), None)
        base = dict(
            key="harvested",
            name="Papers harvested per announcement day",
            question="running",
            rule="red at 0",
            action="Open the Watch run log",
            link="/runs?stage=watch",
            bars=self.days("harvested_bars"),
        )
        if row is None:
            return Tile(**base, state="grey", value="—", why="no successful Watch run yet")
        return Tile(
            **base,
            state="red" if row["value"] == 0 else "green",
            value=str(row["value"]),
            note=f"announcement day {row['day']}",
        )

    def hwm_days(self) -> Tile:
        row = self.q("hwm_days", hwm=HWM, today=self.now.date().isoformat())
        base = dict(
            key="hwm_days",
            name="Days since the high-water mark advanced",
            question="running",
            rule=f"red above {HWM_DAYS}",
            action="Check launchd and the last Watch run",
            link="/runs?stage=watch",
        )
        if row["mark"] is None:
            return Tile(**base, state="grey", value="—", why="no mark yet: Watch hasn't completed")
        return Tile(
            **base,
            state="red" if row["value"] > HWM_DAYS else "green",
            value=str(row["value"]),
            note=f"mark at {row['mark']}",
        )

    def failures(self) -> Tile:
        rows = self.rows("failures", start=self.start, end=self.end)
        given_up = sum(r["given_up"] for r in rows)
        return Tile(
            key="failures",
            name="Stage failures",
            question="running",
            state="red" if rows else "green",
            value=str(len(rows)),
            rule="red at any",
            action="Open the run viewer",
            note="unretried, last 7 days"
            + (f"; {given_up} given up after 3 failures" if given_up else ""),
            link=_failures_link(rows),
            bars=self.days("failures_bars"),
        )

    def candidates(self) -> Tile:
        row = self.q("candidates", start=self.start, end=self.end)
        lo, hi = self.config.alerts.candidates_range
        tile = Tile(
            key="candidates",
            name="Candidates per week",
            question="funnel",
            state="red" if not lo <= row["value"] <= hi else "green",
            value=str(row["value"]),
            rule=f"red outside {lo}–{hi}",
            action="Tighten or loosen keywords",
            note="last 7 days",
            link="/runs?stage=filter&since=7d",
            bars=self.days("candidates"),
        )
        if row["first_filter"] is None:
            return replace(tile, state="grey", value="—", why="no Filter run yet")
        if row["first_filter"] > self.start:
            return replace(tile, state="grey", why="partial week: not judged yet")
        return tile

    def unsupported(self) -> Tile:
        row = self.q("unsupported", start=self.start, end=self.end)
        limit = self.config.alerts.unsupported_rate
        base = dict(
            key="unsupported",
            name="Unsupported-field rate",
            question="right",
            rule=f"red above {limit:.0%}",
            action="Inspect runs; revise the Read prompt or parser",
            link="/runs?stage=read&since=7d",
            bars=self.days("unsupported"),
        )
        if row["value"] is None:
            return Tile(**base, state="grey", value="—", why="no verified Cards yet")
        return Tile(
            **base,
            state="red" if row["value"] > limit else "green",
            value=f"{row['value']:.1%}",
            note=f"{_n(row['cards'], 'Card')}, last 7 days",
        )

    def grounding(self) -> Tile:
        runs = self.rows("grounding")
        base = dict(
            key="grounding",
            name="Grounding rate (Golden)",
            question="right",
            rule=f"red below {GROUNDING_RATE:.0%}",
            action="Revert the change",
            bars=_eval_bars(runs),
        )
        if not runs:
            return Tile(**base, state="grey", value="—", why=NO_EVAL)
        latest = runs[0]
        base |= dict(
            link=f"/eval/{latest['id']}",
            note=f"eval run {latest['id']}, {latest['created_at'][:10]}",
        )
        if latest["value"] is None:
            return Tile(**base, state="grey", value="—", why="no quotes on the latest eval run")
        return Tile(
            **base,
            state="red" if latest["value"] < GROUNDING_RATE else "green",
            value=f"{latest['value']:.1%}",
        )

    def invented(self) -> Tile:
        row = self.q("invented", start=self.start, end=self.end)
        golden = row["golden"] or 0
        if row["card_id"] is not None:
            link = f"/cards/{row['card_id']}/export.md"
        elif row["eval_id"] is not None:
            link = f"/eval/{row['eval_id']}"
        else:
            link = None
        tile = Tile(
            key="invented",
            name="Invented numbers",
            question="right",
            state="red" if row["value"] or golden else "green",
            value=f"{_n(row['value'], 'Card')} · "
            f"{'–' if row['golden'] is None else row['golden']} Golden",
            rule="red at any",
            action="Inspect the Card; this is a hard fail on Golden",
            note="Cards of the last 7 days and the latest eval run",
            link=link,
            bars=self.days("invented"),
        )
        if not row["cards"] and row["eval_id"] is None:
            why = "no Cards in 7 days and no Golden eval run yet"
            return replace(tile, state="grey", value="—", why=why)
        return tile

    def golden_diff(self) -> Tile:
        runs = self.rows("golden_diff")
        base = dict(
            key="golden_diff",
            name="Golden run-to-run diff",
            question="right",
            rule="red with Material changes, until accepted",
            action="Review the diff on /eval/<id> before accepting",
            bars=_eval_bars(runs),
        )
        if not runs:
            return Tile(**base, state="grey", value="—", why=NO_EVAL)
        latest = runs[0]
        base["link"] = f"/eval/{latest['id']}"
        if latest["baseline_id"] is None or latest["value"] is None:
            return Tile(
                **base, state="grey", value="—", why="no baseline: accept a run to make one"
            )
        accepted = latest["accepted_at"] is not None
        return Tile(
            **base,
            state="red" if latest["value"] and not accepted else "green",
            value=f"{latest['value']} Material · {'accepted' if accepted else 'not accepted'}",
            note=f"eval run {latest['id']} vs {latest['baseline_id']}",
        )

    def precision(self) -> Tile:
        row = self.q("precision", start=_iso(self.now - timedelta(days=14)), end=self.end)
        base = dict(
            key="precision",
            name="Filter precision",
            question="useful",
            rule=f"red below {PRECISION:.0%} (from {PRECISION_MIN_REVIEWS} Reviews)",
            action="Add negative keywords or examples",
            link="/runs?stage=filter&since=14d",
            bars=self.days("precision"),
        )
        if not row["reviews"]:
            return Tile(**base, state="grey", value="—", why="no Reviews yet")
        tile = Tile(
            **base,
            state="red" if row["value"] < PRECISION else "green",
            value=f"{row['value']:.0%}",
            note=f"{_n(row['reviews'], 'Review')}, last 14 days",
        )
        if row["reviews"] < PRECISION_MIN_REVIEWS:
            why = f"{_n(row['reviews'], 'Review')}: judged from {PRECISION_MIN_REVIEWS}"
            return replace(tile, state="grey", why=why)
        return tile

    def review_time(self) -> Tile:
        row = self.q("review_time", start=self.start, end=self.end)
        limit = self.config.alerts.review_minutes
        base = dict(
            key="review_time",
            name="Median review time",
            question="useful",
            rule=f"red above {_minutes(limit)}",
            action="Shorten or reorder the Card",
            bars=self.days("review_time"),
        )
        if row["value"] is None:
            return Tile(**base, state="grey", value="—", why="no Reviews yet")
        return Tile(
            **base,
            state="red" if row["value"] > limit else "green",
            value=_minutes(row["value"]),
            note=f"{_n(row['reviews'], 'Review')}, last 7 days",
        )

    def cost_per_card(self) -> Tile:
        row = self.q("cost_per_card", start=self.start, end=self.end)
        by_stage = self.rows("spend_by_stage", start=self.start, end=self.end)
        base = dict(
            key="cost_per_card",
            name="Cost per Carded paper",
            question="affordable",
            action="Find which Stage grew",
            link="/runs?stage=read&since=7d",
            bars=self.days("cost_per_card"),
        )
        if row["value"] is None:
            return Tile(**base, state="grey", value="—", rule="", why="no Carded papers yet")
        note = f"{_n(row['papers'], 'paper')}, last 7 days; spend by Stage: " + " · ".join(
            f"{r['stage']} ${r['usd']:.2f}" for r in by_stage
        )
        first = datetime.fromisoformat(row["first_card"])
        if first + WINDOW > self.now:
            return Tile(
                **base,
                state="grey",
                value=f"${row['value']:.3f}",
                rule="",
                note=note,
                why="baseline forming: week 1 not over",
            )
        week1 = self.q("cost_per_card", start=_iso(first), end=_iso(first + WINDOW))["value"]
        limit = week1 * COST_MULTIPLE
        return Tile(
            **base,
            state="red" if row["value"] > limit else "green",
            value=f"${row['value']:.3f}",
            rule=f"red above ${limit:.3f} ({COST_MULTIPLE}× week 1)",
            note=note,
        )

    def spend(self) -> Tile:
        monday = week_start(self.now.date())
        week = self.q("spend", start=monday.isoformat(), end=self.end)["value"]
        last = self.q(
            "spend", start=(monday - timedelta(days=7)).isoformat(), end=monday.isoformat()
        )["value"]
        budget = self.config.budget.weekly_usd
        return Tile(
            key="spend",
            name="Weekly spend vs guardrail",
            question="affordable",
            state="red" if week >= SPEND_FRACTION * budget else "green",
            value=f"${week:.2f} / ${budget:g}",
            rule=f"red at {SPEND_FRACTION:.0%}",
            action="Check the volume; raise the limit deliberately",
            note=f"{week / budget:.0%} of budget.weekly_usd; last week ${last:.2f}",
            link="/runs?since=week",
            bars=self.days("spend"),
        )

    def minutes_per_relevant(self) -> Tile:
        row = self.q("minutes_per_relevant", start=self.start, end=self.end)
        limit = self.config.alerts.minutes_per_relevant
        base = dict(
            key="minutes_per_relevant",
            name="Reader minutes per relevant paper",
            question="affordable",
            rule=f"red above {limit:g} min",
            action="Find which grew: review time (trim the Card) or the share of"
            ' "no" (tighten the Filter)',
            bars=self.days(
                "minutes_per_relevant", lambda r: r["relevant"] and r["minutes"] / r["relevant"]
            ),
        )
        if not row["reviews"]:
            return Tile(**base, state="grey", value="—", why="no Reviews yet")
        minutes, relevant = row["minutes"], row["relevant"]
        if not relevant:
            return Tile(
                **base,
                state="red",
                value="no relevant paper",
                note=f"{minutes:.0f} Reader min, last 7 days",
            )
        baseline = self.config.roi.baseline_minutes
        multiplier = relevant * baseline / minutes if minutes else 0
        return Tile(
            **base,
            state="red" if minutes / relevant > limit else "green",
            value=f"{minutes / relevant:.1f} min",
            note=f"time multiplier {multiplier:.1f}× ({relevant} relevant × {baseline:g} min"
            f" ÷ {minutes:.0f} Reader min), last 7 days",
        )

    def wasted_minutes(self) -> Tile:
        row = self.q("wasted_minutes", start=self.start, end=self.end)
        limit = self.config.alerts.wasted_minutes
        base = dict(
            key="wasted_minutes",
            name='Minutes spent on "no" Cards',
            question="affordable",
            rule=f"red above {limit:g} min",
            action="Raise filter.threshold or add scope notes",
            bars=self.days("wasted_minutes"),
        )
        if not row["reviews"]:
            return Tile(**base, state="grey", value="—", why="no Reviews yet")
        return Tile(
            **base,
            state="red" if row["value"] > limit else "green",
            value=f"{row['value']:.0f} min",
            note="Reviews rated no, last 7 days",
        )


def _rows(conn: sqlite3.Connection, name: str, **params) -> list[sqlite3.Row]:
    """Run the named query with the parameters it names."""
    sql = QUERIES[name]
    return conn.execute(sql, {k: v for k, v in params.items() if f":{k}" in sql}).fetchall()


def _eval_bars(runs: list[sqlite3.Row]) -> tuple[Bar, ...]:
    """One bar per eval run, oldest first."""
    return tuple(Bar(r["value"] or 0) for r in reversed(runs))


def _failures_link(rows: list[sqlite3.Row]) -> str:
    """`/runs` filtered to the failures: by arXiv id (or the window, when one has no paper),
    plus the Stage and status they share."""
    if not rows:
        return "/runs?" + urlencode({"status": "failed", "since": "7d"})
    stages = {r["stage"] for r in rows}
    statuses = {s for r in rows for s in r["statuses"].split(",")}
    ids = [r["arxiv_id"] for r in rows]
    query = {
        "stage": stages.pop() if len(stages) == 1 else None,
        "status": statuses.pop() if len(statuses) == 1 else None,
        # A failure with no paper (Watch) would be hidden by `ids=`: then the window instead.
        "ids": ",".join(ids) if all(ids) else None,
        "since": None if all(ids) else "7d",
    }
    return "/runs?" + urlencode({k: v for k, v in query.items() if v}, safe=",")


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


def _minutes(minutes: float) -> str:
    """`m:ss`."""
    seconds = round(minutes * 60)
    return f"{seconds // 60}:{seconds % 60:02d}"


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def _weekend(day: date) -> bool:
    return day.weekday() >= 5
