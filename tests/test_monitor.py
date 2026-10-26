import json
import tomllib
from datetime import UTC, datetime
from importlib.resources import files

import pytest

from phy import db
from phy.config import Config
from phy.ui import monitor

# Thursday 2026-10-22, 12:00 UTC. The 7-day window starts Thursday 2026-10-15, 12:00.
NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)


@pytest.fixture
def conn(phy_home):
    phy_home.mkdir()
    conn = db.connect(phy_home / "phy.db")
    conn.execute("PRAGMA foreign_keys = OFF")  # seed rows without their Papers
    yield conn
    conn.close()


@pytest.fixture
def config():
    return Config.model_validate(
        tomllib.loads((files("phy") / "defaults" / "config.toml").read_text())
    )


def at(day: int, hour: int = 6) -> str:
    """A timestamp in October 2026, as the Stages write them."""
    return f"2026-10-{day:02d}T{hour:02d}:00:00+00:00"


def state(conn, key, value):
    conn.execute("INSERT INTO state VALUES (?, ?, ?)", (key, value, value))


def harvested(conn, day: str, n: int, start: int = 0):
    for i in range(start, start + n):
        conn.execute(
            "INSERT INTO paper_versions (arxiv_id, version, submitted_at, first_seen_datestamp)"
            " VALUES (?, 1, ?, ?)",
            (f"2610.{day[-2:]}{i:03d}", day, day),
        )


def run(conn, run_id, stage, started_at, status="ok", arxiv_id=None, cost=None):
    conn.execute(
        "INSERT INTO runs (id, stage, arxiv_id, status, cost_usd, started_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (run_id, stage, arxiv_id, status, cost, started_at),
    )


def screening(conn, arxiv_id, run_id, prefilter="pass", screened_in=False):
    conn.execute(
        "INSERT INTO screenings (arxiv_id, version, prefilter, screened_in, run_id, created_at)"
        " VALUES (?, 1, ?, ?, ?, '')",
        (arxiv_id, prefilter, int(screened_in), run_id),
    )


def card(conn, card_id, run_id, status="verified", supports=("supported",) * 10, invented=()):
    """A Card whose fields carry `supports`; its Paper is 2610.<card_id>."""
    card_json = {
        "tldr": "A flow sampler.",
        "key_results": [{"value": "v", "evidence": [], "support": s} for s in supports],
        "opinion": {"deep_read": {"value": "no"}},
    }
    conn.execute(
        "INSERT INTO cards (id, arxiv_id, version, card_json, status, unsupported_count,"
        " invented_numbers_json, model, prompt_version, schema_version, run_id, created_at,"
        " updated_at) VALUES (?, ?, 1, ?, ?, ?, ?, 'm', 'v2', '1', ?, '', '')",
        (
            card_id,
            f"2610.{card_id:05d}",
            json.dumps(card_json),
            status,
            list(supports).count("unsupported"),
            json.dumps([{"number": n} for n in invented]),
            run_id,
        ),
    )
    return card_id


def eval_run(
    conn,
    eval_id,
    created_at,
    grounding=1.0,
    invented=0,
    split="dev",
    baseline_id=None,
    material=None,
    accepted_at=None,
):
    metrics = {"grounding_rate": grounding, "invented_numbers": invented}
    conn.execute(
        "INSERT INTO eval_runs (id, golden_version, split, prompt_versions_json, model,"
        " metrics_json, per_paper_json, baseline_id, material_changes, accepted_at, created_at)"
        " VALUES (?, 1, ?, '{}', 'm', ?, '[]', ?, ?, ?, ?)",
        (eval_id, split, json.dumps(metrics), baseline_id, material, accepted_at, created_at),
    )


def with_alerts(config, **alerts):
    return config.model_copy(update={"alerts": config.alerts.model_copy(update=alerts)})


def tile(conn, config, key, now=NOW):
    [found] = [t for t in monitor.instruments(conn, config, now) if t.key == key]
    return found


def test_harvested_counts_the_latest_announcement_day_the_last_watch_covered(conn, config):
    state(conn, "watch.last_success_at", at(22))
    harvested(conn, "2026-10-21", 3)
    harvested(conn, "2026-10-22", 5)
    t = tile(conn, config, "harvested")
    assert (t.state, t.value) == ("green", "5")
    assert "2026-10-22" in t.note
    assert t.link == "/runs?stage=watch"


def test_harvested_on_a_weekend_looks_back_to_friday(conn, config):
    state(conn, "watch.last_success_at", "2026-10-18T06:00:00+00:00")  # a Sunday
    harvested(conn, "2026-10-16", 4)
    t = tile(conn, config, "harvested")
    assert (t.state, t.value) == ("green", "4")
    assert "2026-10-16" in t.note


def test_harvested_is_red_at_zero(conn, config):
    state(conn, "watch.last_success_at", at(22))
    harvested(conn, "2026-10-21", 3)
    assert tile(conn, config, "harvested").state == "red"


def test_harvested_is_grey_before_any_successful_watch(conn, config):
    t = tile(conn, config, "harvested")
    assert t.state == "grey"
    assert t.why == "no successful Watch run yet"


def test_harvested_bars_are_the_last_7_days_with_weekends_grey(conn, config):
    state(conn, "watch.last_success_at", at(22))
    harvested(conn, "2026-10-16", 2)
    harvested(conn, "2026-10-22", 5)
    bars = tile(conn, config, "harvested").bars
    assert [b.value for b in bars] == [2, 0, 0, 0, 0, 0, 5]  # Fri 16 .. Thu 22
    assert [b.weekend for b in bars] == [False, True, True, False, False, False, False]


def test_mark_days_counts_announcement_days_after_the_mark(conn, config):
    state(conn, "watch.hwm", "2026-10-20")  # Tuesday: Wed and Thu since
    t = tile(conn, config, "hwm_days")
    assert (t.state, t.value) == ("green", "2")
    assert t.note == "mark at 2026-10-20"


def test_mark_days_skips_weekends_and_is_red_above_2(conn, config):
    state(conn, "watch.hwm", "2026-10-16")  # Friday: Mon to Thu since
    t = tile(conn, config, "hwm_days")
    assert (t.state, t.value) == ("red", "4")


def test_mark_days_is_grey_before_the_first_mark(conn, config):
    t = tile(conn, config, "hwm_days")
    assert (t.state, t.why) == ("grey", "no mark yet: Watch hasn't completed")


def test_failures_count_unretried_failed_and_aborted_runs_per_stage_and_paper(conn, config):
    run(conn, "f1", "read", at(20), "failed", "2610.00001")
    run(conn, "f2", "read", at(21), "failed", "2610.00002")
    run(conn, "ok2", "read", at(21, 7), "ok", "2610.00002")  # retried
    run(conn, "a3", "read", at(21), "aborted", "2610.00003")
    run(conn, "s4", "read", at(21), "skipped", "2610.00004")  # too long: not a failure
    run(conn, "f5", "read", at(14), "failed", "2610.00005")  # before the 7 days
    t = tile(conn, config, "failures")
    assert (t.state, t.value) == ("red", "2")
    assert t.link == "/runs?stage=read&ids=2610.00001,2610.00003"


def test_a_later_skipped_run_is_not_a_retry(conn, config):
    run(conn, "f1", "read", at(20), "failed", "2610.00001")
    run(conn, "s1", "read", at(21), "skipped", "2610.00001")
    assert tile(conn, config, "failures").value == "1"


def test_a_paper_given_up_after_3_failures_counts_once(conn, config):
    for day in [19, 20, 21]:
        run(conn, f"f{day}", "read", at(day), "failed", "2610.00001")
    t = tile(conn, config, "failures")
    assert (t.state, t.value) == ("red", "1")
    assert t.note == "unretried, last 7 days; 1 given up after 3 failures"
    assert t.link == "/runs?stage=read&status=failed&ids=2610.00001"


def test_failures_over_many_stages_link_without_a_stage(conn, config):
    run(conn, "w", "watch", at(20), "failed")
    run(conn, "f", "filter", at(21), "failed", "2610.00001")
    t = tile(conn, config, "failures")
    assert t.value == "2"
    assert t.link == "/runs?status=failed&since=7d"


def test_a_watch_failure_links_to_the_failed_watch_runs(conn, config):
    run(conn, "w", "watch", at(20), "failed")
    assert tile(conn, config, "failures").link == "/runs?stage=watch&status=failed&since=7d"


def test_no_failures_is_green(conn, config):
    run(conn, "ok", "read", at(20), "ok", "2610.00001")
    t = tile(conn, config, "failures")
    assert (t.state, t.value, t.link) == ("green", "0", "/runs?status=failed&since=7d")


def screen(conn, run_id, day, n, prefilter="pass", start=0):
    run(conn, run_id, "filter", at(day))
    for i in range(start, start + n):
        screening(conn, f"2610.{day:02d}{i:03d}", run_id, prefilter)


def test_candidates_count_the_pre_filter_passes_of_the_last_7_days(conn, config):
    config = with_alerts(config, candidates_range=(2, 4))
    screen(conn, "f-old", 8, 5)  # Filter has run for over 7 days; these are before the window
    screen(conn, "f20", 20, 2)
    screen(conn, "f21", 21, 1, prefilter="skipped")  # a set without a pre-filter
    screen(conn, "f22", 22, 3, prefilter="fail")
    t = tile(conn, config, "candidates")
    assert (t.state, t.value) == ("green", "3")
    assert t.rule == "red outside 2–4"
    assert t.link == "/runs?stage=filter&since=7d"
    assert [b.value for b in t.bars] == [0, 0, 0, 0, 2, 1, 0]  # 16 .. 22


def test_candidates_are_red_outside_the_range(conn, config):
    config = with_alerts(config, candidates_range=(2, 4))
    screen(conn, "f-old", 8, 1)
    screen(conn, "f20", 20, 5)
    assert tile(conn, config, "candidates").state == "red"


def test_candidates_are_not_judged_until_filter_has_run_7_days(conn, config):
    screen(conn, "f20", 20, 5)
    t = tile(conn, config, "candidates")
    assert (t.state, t.value, t.why) == ("grey", "5", "partial week: not judged yet")


def test_candidates_are_grey_before_any_filter_run(conn, config):
    t = tile(conn, config, "candidates")
    assert (t.state, t.why) == ("grey", "no Filter run yet")


def read(conn, run_id, day, card_id, cost=None, **card_columns):
    """A Read run on the day and the Card it wrote."""
    run(conn, run_id, "read", at(day), arxiv_id=f"2610.{card_id:05d}", cost=cost)
    return card(conn, card_id, run_id, **card_columns)


UNS = "unsupported"
SUP = "supported"


def test_unsupported_rate_divides_by_the_fields_carrying_a_support(conn, config):
    read(conn, "r1", 20, 1, supports=[UNS] + [SUP] * 9)
    read(conn, "r2", 21, 2, supports=["inferred"] * 2 + [SUP] * 8)
    read(conn, "r3", 21, 3, status="draft", supports=[UNS] * 10)  # not verified yet
    read(conn, "r4", 14, 4, supports=[UNS] * 10)  # before the window
    t = tile(conn, config, "unsupported")
    assert (t.state, t.value) == ("green", "5.0%")
    assert t.note == "2 Cards, last 7 days"
    assert t.rule == "red above 10%"
    assert t.link == "/runs?stage=read&since=7d"
    assert [b.value for b in t.bars] == [0, 0, 0, 0, 0.1, 0, 0]


def test_unsupported_rate_is_red_above_the_alert(conn, config):
    read(conn, "r1", 20, 1, supports=[UNS] * 2 + [SUP] * 8)
    assert tile(conn, config, "unsupported").state == "red"


def test_unsupported_rate_is_grey_without_verified_cards(conn, config):
    read(conn, "r1", 20, 1, status="draft")
    t = tile(conn, config, "unsupported")
    assert (t.state, t.why) == ("grey", "no verified Cards yet")


def test_grounding_is_the_latest_eval_runs_with_the_last_7_runs_as_bars(conn, config):
    for i in range(8):
        eval_run(conn, f"e{i}", at(10 + i), grounding=0.91 + i / 100)
    t = tile(conn, config, "grounding")
    assert (t.state, t.value) == ("green", "98.0%")
    assert t.note == "eval run e7, 2026-10-17"
    assert t.link == "/eval/e7"
    assert [round(b.value, 2) for b in t.bars] == [0.92, 0.93, 0.94, 0.95, 0.96, 0.97, 0.98]
    assert not any(b.weekend for b in t.bars)


def test_grounding_is_red_below_98_percent(conn, config):
    eval_run(conn, "e1", at(20), grounding=0.979)
    assert tile(conn, config, "grounding").state == "red"


def test_grounding_is_grey_without_an_eval_run_or_quotes(conn, config):
    t = tile(conn, config, "grounding")
    assert (t.state, t.why, t.link) == ("grey", "no Golden eval run yet: run phy eval", None)
    eval_run(conn, "e1", at(20), grounding=None)
    t = tile(conn, config, "grounding")
    assert (t.state, t.why) == ("grey", "no quotes on the latest eval run")


def test_invented_numbers_on_a_recent_card_are_red_and_link_to_the_card(conn, config):
    read(conn, "r1", 20, 1)
    read(conn, "r2", 21, 2, invented=["0.42"])
    read(conn, "r3", 14, 3, invented=["7"])  # before the window
    eval_run(conn, "e1", at(19), invented=0)
    t = tile(conn, config, "invented")
    assert (t.state, t.value) == ("red", "1 Card · 0 Golden")
    assert t.link == "/cards/2/export.md"
    assert [b.value for b in t.bars] == [0, 0, 0, 0, 0, 1, 0]


def test_invented_numbers_on_the_latest_eval_run_link_to_it(conn, config):
    eval_run(conn, "e1", at(18), invented=2)
    eval_run(conn, "e2", at(19), invented=1)
    t = tile(conn, config, "invented")
    assert (t.state, t.value, t.link) == ("red", "0 Cards · 1 Golden", "/eval/e2")


def test_no_invented_numbers_is_green(conn, config):
    read(conn, "r1", 20, 1)
    t = tile(conn, config, "invented")
    assert (t.state, t.value) == ("green", "0 Cards · – Golden")


def test_invented_numbers_are_grey_without_cards_or_an_eval_run(conn, config):
    t = tile(conn, config, "invented")
    assert (t.state, t.why) == ("grey", "no Cards in 7 days and no Golden eval run yet")


def test_golden_diff_is_red_while_material_changes_are_unaccepted(conn, config):
    eval_run(conn, "e1", at(18), accepted_at=at(18, 9))
    eval_run(conn, "e2", at(20), baseline_id="e1", material=3)
    eval_run(conn, "h1", at(21), split="held_out")  # Material changes are on Dev
    t = tile(conn, config, "golden_diff")
    assert (t.state, t.value) == ("red", "3 Material · not accepted")
    assert t.note == "eval run e2 vs e1"
    assert t.link == "/eval/e2"
    assert [b.value for b in t.bars] == [0, 3]


def test_golden_diff_is_green_once_accepted_or_without_material_changes(conn, config):
    eval_run(conn, "e1", at(18), accepted_at=at(18, 9))
    eval_run(conn, "e2", at(20), baseline_id="e1", material=3, accepted_at=at(20, 9))
    assert tile(conn, config, "golden_diff").value == "3 Material · accepted"
    assert tile(conn, config, "golden_diff").state == "green"
    eval_run(conn, "e3", at(21), baseline_id="e2", material=0)
    assert tile(conn, config, "golden_diff").state == "green"


def test_golden_diff_is_grey_without_an_eval_run_or_a_baseline(conn, config):
    t = tile(conn, config, "golden_diff")
    assert (t.state, t.why) == ("grey", "no Golden eval run yet: run phy eval")
    eval_run(conn, "e1", at(20))
    t = tile(conn, config, "golden_diff")
    assert (t.state, t.why, t.link) == ("grey", "no baseline: accept a run to make one", "/eval/e1")


def review(conn, relevance, seconds, created_at, deep_read=False, card_id=1):
    conn.execute(
        "INSERT INTO reviews (card_id, relevance, deep_read, seconds_spent, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (card_id, relevance, int(deep_read), seconds, created_at),
    )


def reviews(conn, day, **counts):
    """`counts` Reviews of each relevance on the day, 4 minutes each."""
    for relevance, n in counts.items():
        for _ in range(n):
            review(conn, relevance, 240, at(day))


def test_precision_is_the_share_of_yes_or_partly_over_14_days(conn, config):
    reviews(conn, 10, yes=8, partly=2, no=4)  # 12 days ago
    reviews(conn, 21, yes=4, no=2)
    reviews(conn, 7, no=10)  # 15 days ago: outside the window
    t = tile(conn, config, "precision")
    assert (t.state, t.value) == ("green", "70%")
    assert t.note == "20 Reviews, last 14 days"
    assert t.link == "/runs?stage=filter&since=14d"


def test_precision_is_red_below_70_percent(conn, config):
    reviews(conn, 21, yes=13, no=7)
    assert tile(conn, config, "precision").state == "red"


def test_precision_is_not_judged_before_20_reviews(conn, config):
    reviews(conn, 21, yes=1, no=4)
    t = tile(conn, config, "precision")
    assert (t.state, t.value, t.why) == ("grey", "20%", "5 Reviews: judged from 20")
    t = tile(conn, config, "precision", now=datetime(2026, 11, 20, tzinfo=UTC))
    assert (t.state, t.why) == ("grey", "no Reviews yet")


def test_review_time_is_the_median_of_the_last_7_days(conn, config):
    for seconds in [200, 240, 400]:
        review(conn, "yes", seconds, at(21))
    review(conn, "yes", 900, at(14))  # before the window
    t = tile(conn, config, "review_time")
    assert (t.state, t.value) == ("green", "4:00")
    assert t.rule == "red above 5:00"
    assert t.note == "3 Reviews, last 7 days"
    assert [b.value for b in t.bars] == [0, 0, 0, 0, 0, 4, 0]


def test_review_time_is_red_above_the_alert(conn, config):
    for seconds in [290, 340]:
        review(conn, "yes", seconds, at(21))
    t = tile(conn, config, "review_time")
    assert (t.state, t.value) == ("red", "5:15")


def test_review_time_is_grey_without_reviews(conn, config):
    t = tile(conn, config, "review_time")
    assert (t.state, t.why) == ("grey", "no Reviews yet")


def carded(conn, card_id, day, *costs, stage="read"):
    """A Card on the day, and one run per cost tied to its Paper (the first one wrote it)."""
    arxiv_id = f"2610.{card_id:05d}"
    for i, cost in enumerate(costs):
        run(conn, f"c{card_id}-{i}", stage, at(day, 6 + i), arxiv_id=arxiv_id, cost=cost)
    card(conn, card_id, f"c{card_id}-0")


def test_cost_per_carded_paper_is_the_median_of_every_run_on_the_paper(conn, config):
    carded(conn, 1, 1, 0.10)  # week 1: Oct 1 to 8, median $0.10
    carded(conn, 2, 2, 0.10)
    carded(conn, 3, 3, 0.12)
    carded(conn, 4, 20, 0.12, 0.03)  # a retried Read: both count
    carded(conn, 5, 21, 0.10)
    run(conn, "f", "filter", at(21), cost=0.05)  # not tied to a Paper
    run(conn, "g", "golden", at(21), arxiv_id="2610.00005", cost=5.0)  # Golden, not pipeline
    t = tile(conn, config, "cost_per_card")
    assert (t.state, t.value) == ("green", "$0.125")
    assert t.rule == "red above $0.200 (2× week 1)"
    assert (
        t.note == "2 papers, last 7 days; spend by Stage: golden $5.00 · read $0.25 · filter $0.05"
    )
    assert t.link == "/runs?stage=read&since=7d"


def test_cost_per_carded_paper_is_red_above_twice_week_1(conn, config):
    carded(conn, 1, 1, 0.10)
    carded(conn, 2, 20, 0.21)
    assert tile(conn, config, "cost_per_card").state == "red"


def test_cost_per_carded_paper_waits_for_week_1(conn, config):
    carded(conn, 1, 18, 0.10)
    t = tile(conn, config, "cost_per_card")
    assert (t.state, t.value, t.why) == ("grey", "$0.100", "baseline forming: week 1 not over")
    t = tile(conn, config, "cost_per_card", now=datetime(2026, 10, 10, tzinfo=UTC))
    assert (t.state, t.why) == ("grey", "no Carded papers yet")


def test_weekly_spend_is_the_iso_week_and_red_at_90_percent(conn, config):
    run(conn, "sun", "read", "2026-10-18T23:00:00+00:00", cost=5.0)  # last week
    run(conn, "mon", "read", at(19), cost=10.0)
    run(conn, "wed", "read", at(21), cost=7.0)
    t = tile(conn, config, "spend")
    assert (t.state, t.value) == ("green", "$17.00 / $20")
    assert t.note == "85% of budget.weekly_usd; last week $5.00"
    assert t.rule == "red at 90%"
    assert t.link == "/runs?since=week"
    assert [b.value for b in t.bars] == [0, 0, 5.0, 10.0, 0, 7.0, 0]
    run(conn, "thu", "read", at(22), cost=1.0)
    assert tile(conn, config, "spend").state == "red"


def test_reader_minutes_per_relevant_paper_carries_the_time_multiplier(conn, config):
    reviews(conn, 21, yes=2, partly=1, no=1)  # 16 minutes, 3 relevant
    t = tile(conn, config, "minutes_per_relevant")
    assert (t.state, t.value) == ("green", "5.3 min")
    assert t.rule == "red above 8 min"
    assert t.note == "time multiplier 2.8× (3 relevant × 15 min ÷ 16 Reader min), last 7 days"


def test_reader_minutes_per_relevant_paper_is_red_above_the_alert(conn, config):
    reviews(conn, 21, yes=1, no=2)
    assert tile(conn, config, "minutes_per_relevant").state == "red"
    reviews(conn, 20, no=1)
    t = tile(conn, config, "minutes_per_relevant", now=datetime(2026, 10, 20, 12, tzinfo=UTC))
    assert (t.state, t.value) == ("red", "no relevant paper")


def test_reader_minutes_per_relevant_paper_is_grey_without_reviews(conn, config):
    t = tile(conn, config, "minutes_per_relevant")
    assert (t.state, t.why) == ("grey", "no Reviews yet")


def test_minutes_on_no_cards_sum_the_reviews_rated_no(conn, config):
    reviews(conn, 21, yes=3, no=2)
    t = tile(conn, config, "wasted_minutes")
    assert (t.state, t.value) == ("green", "8 min")
    assert t.rule == "red above 40 min"
    reviews(conn, 20, no=9)  # 44 minutes in all
    assert tile(conn, config, "wasted_minutes").state == "red"


def test_minutes_on_no_cards_are_grey_without_reviews(conn, config):
    t = tile(conn, config, "wasted_minutes")
    assert (t.state, t.why) == ("grey", "no Reviews yet")


def test_every_instrument_of_the_spec_table_in_order(conn, config):
    keys = [t.key for t in monitor.instruments(conn, config, NOW)]
    assert keys == [
        "harvested",
        "hwm_days",
        "failures",
        "candidates",
        "unsupported",
        "grounding",
        "invented",
        "golden_diff",
        "precision",
        "review_time",
        "cost_per_card",
        "spend",
        "minutes_per_relevant",
        "wasted_minutes",
    ]


def test_the_funnel_counts_a_week_of_activity_with_each_steps_share(conn, config):
    harvested(conn, "2026-10-20", 4)
    harvested(conn, "2026-10-10", 9)  # before the window
    run(conn, "f20", "filter", at(20))
    for i, (prefilter, screened_in) in enumerate(
        [("pass", True), ("pass", True), ("skipped", False), ("fail", False)]
    ):
        screening(conn, f"2610.2000{i}", "f20", prefilter, screened_in)
    read(conn, "r1", 21, 1)
    read(conn, "r2", 21, 2, status="draft")
    for relevance, deep_read in [("yes", False), ("partly", True), ("no", False)]:
        review(conn, relevance, 240, at(21, 9), deep_read)  # last week's Cards too
    run(conn, "s1", "read", at(21), "skipped", "2610.00009")
    run(conn, "s0", "read", at(14), "skipped", "2610.00008")  # before the window
    f = monitor.funnel(conn, NOW)
    assert [(s.key, s.count) for s in f.steps] == [
        ("harvested", 4),
        ("candidates", 3),
        ("screened_in", 2),
        ("carded", 2),
        ("verified", 1),
        ("reviewed", 3),
        ("relevant", 2),
        ("deep_read", 1),
    ]
    assert [None if s.share is None else round(s.share * 100) for s in f.steps] == [
        None,
        75,
        67,
        100,
        50,
        300,
        67,
        50,
    ]
    assert f.skipped_too_long == 1


def test_a_step_after_an_empty_one_has_no_share(conn, config):
    f = monitor.funnel(conn, NOW)
    assert [s.share for s in f.steps] == [None] * 8


def test_cost_per_carded_paper_takes_papers_carded_in_the_window_with_all_their_runs(conn, config):
    carded(conn, 1, 1, 0.10)  # week 1
    run(conn, "old-try", "read", at(12), "failed", "2610.00002", cost=0.04)  # 10 days ago
    carded(conn, 2, 21, 0.10)
    run(conn, "late", "verify", at(21), arxiv_id="2610.00001", cost=0.50)  # Carded on day 1
    t = tile(conn, config, "cost_per_card")
    assert (t.value, t.note.split(";")[0]) == ("$0.140", "1 paper, last 7 days")


def test_review_time_ignores_reviews_without_a_time(conn, config):
    for seconds in [None, None, 240]:
        review(conn, "yes", seconds, at(21))
    assert tile(conn, config, "review_time").value == "4:00"


def test_failures_with_and_without_a_paper_link_without_ids(conn, config):
    run(conn, "w", "watch", at(20), "failed")
    run(conn, "r", "read", at(21), "failed", "2610.00001")
    assert tile(conn, config, "failures").link == "/runs?status=failed&since=7d"


def test_a_paper_retried_ok_since_its_failures_is_not_given_up(conn, config):
    for day in [16, 17, 18]:
        run(conn, f"f{day}", "read", at(day), "failed", "2610.00001")
    run(conn, "ok", "read", at(19), "ok", "2610.00001")
    run(conn, "f20", "read", at(20), "failed", "2610.00001")
    assert tile(conn, config, "failures").note == "unretried, last 7 days"
