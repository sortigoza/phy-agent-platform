from datetime import UTC, date, datetime
from importlib.resources import files

import pytest

from phy import db
from phy.arxiv import ArxivRecord, Version
from phy.config import resolve_paths
from phy.ctx import Ctx
from phy.read.select import Candidate, plan, select

MONDAY, TUESDAY, WEDNESDAY = date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)
SUNDAY_BEFORE = date(2026, 10, 18)


def c(n, score):
    return Candidate(arxiv_id=f"2610.{n:05d}", version=1, best_score=score)


def ids(picks):
    return [p.arxiv_id[-2:] for p in picks]


@pytest.mark.parametrize(
    ("candidates", "recards", "used", "today", "expected"),
    [
        # the highest-scoring first, up to the day's quota of 2
        ([c(1, 0.5), c(2, 0.8), c(3, 0.6)], [], {}, MONDAY, ["02", "03"]),
        # every Paper over always_threshold, even past the quota; nothing else then
        ([c(1, 0.95), c(2, 0.9), c(3, 0.92), c(4, 0.8)], [], {}, MONDAY, ["01", "03", "02"]),
        # the always ones use the quota up first
        ([c(1, 0.95), c(2, 0.8), c(3, 0.7)], [], {}, MONDAY, ["01", "02"]),
        # already read today counts
        ([c(1, 0.8), c(2, 0.7)], [], {MONDAY: 1}, MONDAY, ["01"]),
        ([c(1, 0.8)], [], {MONDAY: 2}, MONDAY, []),
        # unused quota of Monday and Tuesday carries over to Wednesday
        ([c(n, 0.6) for n in range(1, 9)], [], {}, WEDNESDAY, ["01", "02", "03", "04", "05", "06"]),
        (
            [c(n, 0.6) for n in range(1, 9)],
            [],
            {MONDAY: 1},
            WEDNESDAY,
            ["01", "02", "03", "04", "05"],
        ),
        # an over-quota Monday leaves no negative carry
        ([c(n, 0.6) for n in range(1, 9)], [], {MONDAY: 5}, TUESDAY, ["01", "02"]),
        # last week's unused quota does not carry
        ([c(n, 0.6) for n in range(1, 9)], [], {SUNDAY_BEFORE: 0}, MONDAY, ["01", "02"]),
        # Stale re-cards count toward the quota and go before the score-ranked others
        ([c(1, 0.8), c(2, 0.7)], [c(9, 0.3)], {}, MONDAY, ["09", "01"]),
        # a re-card that is also a Candidate is picked once
        ([c(1, 0.8), c(9, 0.7)], [c(9, 0.7)], {}, MONDAY, ["09", "01"]),
        ([c(9, 0.95)], [c(9, 0.95)], {}, MONDAY, ["09"]),
    ],
)
def test_plan(candidates, recards, used, today, expected):
    picks = plan(
        candidates, recards, used, today, daily_quota=2, always_threshold=0.9, weekly_ceiling=50
    )
    assert ids(picks) == expected


def test_the_weekly_ceiling_caps_even_the_always_ones():
    used = {MONDAY: 3, TUESDAY: 3}
    candidates = [c(1, 0.99), c(2, 0.95), c(3, 0.9), c(4, 0.6)]
    picks = plan(
        candidates, [], used, WEDNESDAY, daily_quota=2, always_threshold=0.9, weekly_ceiling=8
    )
    assert ids(picks) == ["01", "02"]


def test_picks_say_why():
    picks = plan(
        [c(1, 0.95), c(2, 0.6)],
        [c(9, 0.3)],
        {},
        MONDAY,
        daily_quota=3,
        always_threshold=0.9,
        weekly_ceiling=50,
    )
    assert [p.reason for p in picks] == ["always", "recard", "quota"]


# `select()`: the same rule, fed from the database, behind the weekly spend guardrail.

THURSDAY = date(2026, 10, 22)


def paper(arxiv_id, versions=1):
    return ArxivRecord(
        arxiv_id=arxiv_id,
        datestamp=date(2026, 10, 19),
        sets=["physics:hep-lat"],
        title="A lattice paper",
        authors="A. Author",
        abstract="An abstract.",
        categories=["hep-lat"],
        license=None,
        versions=[
            Version(number=n, submitted_at=datetime(2026, 10, n, tzinfo=UTC))
            for n in range(1, versions + 1)
        ],
    )


@pytest.fixture
def ctx(phy_home):
    phy_home.mkdir()
    for name in ["config.toml", "questions.yaml"]:
        (phy_home / name).write_bytes((files("phy") / "defaults" / name).read_bytes())
    ctx = Ctx.load(resolve_paths())
    yield ctx
    ctx.db.close()


def run_row(ctx, run_id, stage, started_at, cost_usd=0.0, arxiv_id=None):
    ctx.db.execute(
        "INSERT INTO runs (id, stage, arxiv_id, status, cost_usd, started_at)"
        " VALUES (?, ?, ?, 'ok', ?, ?)",
        (run_id, stage, arxiv_id, cost_usd, started_at),
    )
    ctx.db.commit()


def screened(ctx, arxiv_id, version, score, threshold=0.5):
    run_row(ctx, f"f-{arxiv_id}v{version}", "filter", "2026-10-19T06:00:00+00:00")
    db.write_screening(
        ctx.db,
        arxiv_id=arxiv_id,
        version=version,
        prefilter="skipped",
        scores_json="{}",
        best_score=score,
        screened_in=score >= threshold,
        model="claude-haiku-5-5",
        prompt_version="v1",
        run_id=f"f-{arxiv_id}v{version}",
    )


def carded(ctx, arxiv_id, version, read_at="2026-10-19T06:00:00+00:00", cost_usd=0.1):
    run_id = f"r-{arxiv_id}v{version}"
    run_row(ctx, run_id, "read", read_at, cost_usd, arxiv_id)
    return db.write_draft_card(
        ctx.db, arxiv_id, version, "{}", "claude-sonnet-5-5", "v2", "card/v1", run_id
    )


def reviewed(ctx, card_id, *relevances):
    for n, relevance in enumerate(relevances):
        ctx.db.execute(
            "INSERT INTO reviews (card_id, relevance, created_at) VALUES (?, ?, ?)",
            (card_id, relevance, f"2026-10-19T0{n}:00:00+00:00"),
        )
    ctx.db.commit()


def test_select_takes_screened_in_latest_versions_without_a_card(ctx):
    for n in range(1, 6):
        db.upsert_paper(ctx.db, paper(f"2610.0000{n}", versions=2 if n == 4 else 1))
    screened(ctx, "2610.00001", 1, 0.7)
    screened(ctx, "2610.00002", 1, 0.4)  # screened out
    screened(ctx, "2610.00003", 1, 0.8)
    carded(ctx, "2610.00003", 1)  # already Carded
    screened(ctx, "2610.00004", 1, 0.9)  # an older version's screening
    screened(ctx, "2610.00005", 1, 0.6)

    picks = select(ctx, THURSDAY)

    assert [(p.arxiv_id, p.version, p.reason) for p in picks] == [
        ("2610.00001", 1, "quota"),
        ("2610.00005", 1, "quota"),
    ]


def test_cards_read_this_week_use_the_quota(ctx):
    for n in range(1, 31):
        db.upsert_paper(ctx.db, paper(f"2610.{n:05d}"))
        screened(ctx, f"2610.{n:05d}", 1, 0.6)
    for n in range(21, 31):  # 10 Read on Monday, against 8 a day
        carded(ctx, f"2610.{n:05d}", 1, read_at="2026-10-19T06:00:00+00:00")
    carded_last_week = "2610.00020"
    carded(ctx, carded_last_week, 1, read_at="2026-10-18T06:00:00+00:00")

    picks = select(ctx, TUESDAY)

    assert len(picks) == 8  # Monday's overrun carries nothing


@pytest.mark.parametrize(
    ("recard_stale", "relevances", "expected"),
    [
        ("relevant_only", ["yes"], True),
        ("relevant_only", ["partly"], True),
        ("relevant_only", ["yes", "no"], False),  # the latest Review counts
        ("relevant_only", ["no", "partly"], True),
        ("relevant_only", [], False),
        ("all", [], True),
        ("never", ["yes"], False),
    ],
)
def test_stale_cards_are_re_carded_by_their_review(ctx, recard_stale, relevances, expected):
    ctx.config = ctx.config.model_copy(
        update={"read": ctx.config.read.model_copy(update={"recard_stale": recard_stale})}
    )
    db.upsert_paper(ctx.db, paper("2610.00001"))
    card_id = carded(ctx, "2610.00001", 1)
    reviewed(ctx, card_id, *relevances)
    db.upsert_paper(ctx.db, paper("2610.00001", versions=2))
    db.mark_cards_stale(ctx.db, "2610.00001", 2)

    picks = select(ctx, THURSDAY)

    assert [(p.arxiv_id, p.version, p.reason) for p in picks] == (
        [("2610.00001", 2, "recard")] if expected else []
    )


def test_a_re_carded_paper_is_not_picked_again(ctx):
    db.upsert_paper(ctx.db, paper("2610.00001"))
    reviewed(ctx, carded(ctx, "2610.00001", 1), "yes")
    db.upsert_paper(ctx.db, paper("2610.00001", versions=2))
    db.mark_cards_stale(ctx.db, "2610.00001", 2)
    carded(ctx, "2610.00001", 2)

    assert select(ctx, THURSDAY) == []


def test_the_weekly_guardrail_selects_nothing(ctx, caplog):
    db.upsert_paper(ctx.db, paper("2610.00001"))
    screened(ctx, "2610.00001", 1, 0.95)
    run_row(ctx, "last-week", "read", "2026-10-18T23:00:00+00:00", cost_usd=50.0)
    run_row(ctx, "monday", "read", "2026-10-19T06:00:00+00:00", cost_usd=19.0)
    assert len(select(ctx, THURSDAY)) == 1

    run_row(ctx, "tuesday", "filter", "2026-10-20T06:00:00+00:00", cost_usd=1.0)
    assert select(ctx, THURSDAY) == []
