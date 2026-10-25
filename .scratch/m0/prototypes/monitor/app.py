# /// script
# requires-python = ">=3.13"
# dependencies = ["fastapi==0.115.6", "uvicorn==0.34.0"]
# ///
"""PROTOTYPE, throwaway. Monitoring page for the ticket "Monitoring page layout and the SQL behind each tile".

Three structurally different variants of `/monitor`, switchable via `?variant=A|B|C`
and the floating bar (or ← / →):
  A  Tile wall     tiles grouped by question, sparkline in each, funnel strip on top
  B  Ledger        one table row per Instrument (value, threshold, 7 days, action), red rows first
  C  Triage        only red tiles as action cards, green ones collapsed to chips, 4-week funnel
  D  A + C         C's action list on top of A's tile wall (the Reader's pick)

`?scenario=healthy|broken|fresh` reseeds the scratch DB:
  healthy  4 weeks of normal running
  broken   mark stuck, unretried failure, unsupported 14 %, an invented number,
           an unaccepted Golden diff, spend at 85 %
  fresh    day 2 of M0: most tiles have nothing to compute yet

Every tile is one SQL query in QUERIES, run against PROTOTYPE-wipe-me.db (SPEC §6 tables,
no new columns). The query text is shown on hover via the "sql" toggle (key: q).

Run:  python3 -m venv .venv && .venv/bin/pip install fastapi uvicorn; .venv/bin/python app.py   →  http://127.0.0.1:8001/monitor
"""

import html
import json
import random
import sqlite3
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

HERE = Path(__file__).parent
DB = HERE / "PROTOTYPE-wipe-me.db"
NOW = datetime(2026, 10, 26, 7, 30)  # a Monday morning: the weekly glance (SPEC §11)

CONFIG = {
    "alerts.candidates_range": (100, 400),
    "alerts.unsupported_rate": 0.10,
    "alerts.review_minutes": 5,
    "alerts.grounding_rate": 0.98,
    "alerts.precision": 0.70,
    "alerts.precision_min_reviews": 20,
    "alerts.cost_multiple": 2.0,
    "alerts.hwm_days": 2,
    "alerts.spend_fraction": 0.80,
    "budget.weekly_usd": 20.0,
}

SCHEMA = """
CREATE TABLE papers (arxiv_id TEXT PRIMARY KEY, latest_version INT, title TEXT, authors TEXT, abstract TEXT,
  categories TEXT, primary_category TEXT, license TEXT, sets TEXT, first_seen_at TEXT, updated_at TEXT);
CREATE TABLE paper_versions (arxiv_id TEXT, version INT, submitted_at TEXT, first_seen_datestamp TEXT,
  source_type TEXT, local_path TEXT, sha256 TEXT, fetched_at TEXT, PRIMARY KEY (arxiv_id, version));
CREATE TABLE state (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE screenings (arxiv_id TEXT, version INT, prefilter TEXT, scores_json TEXT, best_score REAL,
  screened_in INT, model TEXT, prompt_version TEXT, run_id INT);
CREATE TABLE cards (id INTEGER PRIMARY KEY, arxiv_id TEXT, version INT, card_json TEXT, status TEXT,
  unsupported_count INT, inferred_count INT, invented_numbers_json TEXT, warnings_json TEXT, model TEXT,
  prompt_version TEXT, schema_version INT, run_id INT);
CREATE TABLE reviews (card_id INT, relevance TEXT, deep_read INT, seconds_spent INT, note TEXT, created_at TEXT);
CREATE TABLE flags (card_id INT, field_path TEXT, kind TEXT, note TEXT, created_at TEXT);
CREATE TABLE runs (id INTEGER PRIMARY KEY, stage TEXT, arxiv_id TEXT, status TEXT, error TEXT, model TEXT,
  prompt_version TEXT, tokens_in INT, tokens_out INT, cache_read_tokens INT, cost_usd REAL,
  started_at TEXT, ended_at TEXT, log_path TEXT);
CREATE TABLE eval_runs (id INTEGER PRIMARY KEY, golden_version INT, split TEXT, prompt_versions_json TEXT,
  model TEXT, metrics_json TEXT, per_paper_json TEXT, baseline_id INT, diff_json TEXT, material_changes INT,
  accepted_at TEXT, created_at TEXT);
CREATE INDEX runs_started ON runs (started_at);
CREATE INDEX runs_stage ON runs (stage, arxiv_id, started_at);
"""

# --- the queries: one per tile. Params: :start, :end (UTC 'YYYY-MM-DD HH:MM:SS'), :now ------------------

QUERIES = {
    "harvested": """
-- Paper versions first carried by the most recent announcement day the last successful Watch covered
WITH target AS (
  -- the latest Mon–Fri on or before the last Watch success
  SELECT date(value, '-' || CASE strftime('%w', value) WHEN '0' THEN 2 WHEN '6' THEN 1 ELSE 0 END || ' days') AS day
  FROM state WHERE key = 'watch.last_success_at'
)
SELECT target.day AS label,
       (SELECT count(*) FROM paper_versions WHERE first_seen_datestamp = target.day) AS value
FROM target""",
    "harvested_series": """
SELECT count(*) AS value, strftime('%w', :start) BETWEEN '1' AND '5' AS announcement
FROM paper_versions WHERE first_seen_datestamp = date(:start)""",
    "hwm_days": """
-- the mark moves to the run's responseDate, so its date is the day it last advanced.
-- announcement days = Mon–Fri; arXiv holidays are ignored (a false red about once a year)
WITH RECURSIVE d(day) AS (
  SELECT date((SELECT value FROM state WHERE key = 'watch.hwm'), '+1 day')
  UNION ALL SELECT date(day, '+1 day') FROM d WHERE day < date(:now))
SELECT (SELECT value FROM state WHERE key = 'watch.hwm') AS label, count(*) AS value
FROM d WHERE strftime('%w', day) BETWEEN '1' AND '5' AND day <= date(:now)""",
    "failures": """
-- failed runs in the window with no later ok run of the same Stage (and same paper, for per-paper Stages)
SELECT count(*) AS value, group_concat(f.id) AS run_ids
FROM runs f
WHERE f.status = 'failed' AND f.started_at >= :start AND f.started_at < :end
  AND NOT EXISTS (SELECT 1 FROM runs r WHERE r.stage = f.stage AND r.arxiv_id IS f.arxiv_id
                  AND r.status = 'ok' AND r.started_at > f.started_at)""",
    "candidates": """
-- Candidates = passed the pre-filter (or the set skips it); dated by the Filter run that screened them
SELECT count(*) AS value
FROM screenings s JOIN runs r ON r.id = s.run_id
WHERE s.prefilter IN ('pass', 'skipped') AND r.started_at >= :start AND r.started_at < :end""",
    "unsupported": """
-- unsupported fields / fields that carry a Support, over Cards Read in the window (drafts excluded)
SELECT sum(c.unsupported_count) * 1.0
         / nullif(sum((SELECT count(*) FROM json_tree(c.card_json) WHERE key = 'support')), 0) AS value,
       count(*) AS n, group_concat(c.run_id) AS run_ids
FROM cards c JOIN runs r ON r.id = c.run_id
WHERE c.status != 'draft' AND r.started_at >= :start AND r.started_at < :end""",
    "grounding": """
-- the latest Golden eval run; its series is the last 7 eval runs, not days
SELECT json_extract(metrics_json, '$.grounding_rate') AS value, id AS eval_id, created_at AS label
FROM eval_runs ORDER BY created_at DESC LIMIT 1""",
    "grounding_series": """
SELECT json_extract(metrics_json, '$.grounding_rate') AS value FROM (
  SELECT * FROM eval_runs ORDER BY created_at DESC LIMIT 7) ORDER BY created_at""",
    "invented": """
-- pipeline Cards with an invented number in the window, plus the latest eval run's count
SELECT (SELECT count(*) FROM cards c JOIN runs r ON r.id = c.run_id
        WHERE json_array_length(c.invented_numbers_json) > 0 AND r.started_at >= :start AND r.started_at < :end) AS cards,
       (SELECT json_extract(metrics_json, '$.invented_numbers') FROM eval_runs ORDER BY created_at DESC LIMIT 1) AS golden,
       (SELECT group_concat(c.id) FROM cards c JOIN runs r ON r.id = c.run_id
        WHERE json_array_length(c.invented_numbers_json) > 0 AND r.started_at >= :start AND r.started_at < :end) AS card_ids""",
    "invented_series": """
SELECT count(*) AS value FROM cards c JOIN runs r ON r.id = c.run_id
WHERE json_array_length(c.invented_numbers_json) > 0 AND r.started_at >= :start AND r.started_at < :end""",
    "golden_diff": """
-- the latest eval run: red while it has Material changes and is not accepted
SELECT id AS eval_id, material_changes AS value, accepted_at, baseline_id, created_at AS label
FROM eval_runs ORDER BY created_at DESC LIMIT 1""",
    "precision": """
-- share of Reviews rated yes or partly, over 2 weeks; red only once there are enough Reviews
SELECT avg(relevance IN ('yes', 'partly')) AS value, count(*) AS n
FROM reviews WHERE created_at >= :start AND created_at < :end""",
    "review_time": """
-- median seconds_spent (SQLite has no median: the middle row, or the mean of the two middle rows)
WITH s AS (SELECT seconds_spent AS x, row_number() OVER (ORDER BY seconds_spent) AS i, count(*) OVER () AS n
           FROM reviews WHERE created_at >= :start AND created_at < :end)
SELECT avg(x) / 60.0 AS value, max(n) AS n FROM s WHERE i IN ((n + 1) / 2, (n + 2) / 2)""",
    "cost_per_card": """
-- median over Carded papers of the cost of every run tied to that paper (Read retries included)
WITH per AS (
  SELECT r.arxiv_id, sum(r.cost_usd) AS x FROM runs r
  WHERE r.arxiv_id IS NOT NULL AND r.started_at >= :start AND r.started_at < :end
    AND EXISTS (SELECT 1 FROM cards c WHERE c.arxiv_id = r.arxiv_id)
  GROUP BY r.arxiv_id),
s AS (SELECT x, row_number() OVER (ORDER BY x) AS i, count(*) OVER () AS n FROM per)
SELECT avg(x) AS value, max(n) AS n FROM s WHERE i IN ((n + 1) / 2, (n + 2) / 2)""",
    "cost_week1": """
-- the baseline: the same median over the 7 days from the first Card's Read run
SELECT min(r.started_at) AS first FROM cards c JOIN runs r ON r.id = c.run_id""",
    "spend": """
-- spend in the current ISO week (Monday 00:00 UTC), which is the window the guardrail enforces
SELECT coalesce(sum(cost_usd), 0) AS value,
       (SELECT coalesce(sum(cost_usd), 0) FROM runs
        WHERE started_at >= date(:now, 'weekday 0', '-13 days') AND started_at < date(:now, 'weekday 0', '-6 days')) AS last_week
FROM runs WHERE started_at >= date(:now, 'weekday 0', '-6 days')""",
    "spend_by_stage": """
SELECT stage, round(sum(cost_usd), 2) AS usd FROM runs
WHERE started_at >= date(:now, '-7 days') GROUP BY stage ORDER BY usd DESC""",
    "spend_series": """
SELECT coalesce(sum(cost_usd), 0) AS value FROM runs WHERE started_at >= :start AND started_at < :end""",
}

# the funnel: activity in the window, one count per step
FUNNEL_SQL = """
SELECT
 (SELECT count(*) FROM paper_versions WHERE first_seen_datestamp > date(:start) AND first_seen_datestamp <= date(:end)) AS harvested,
 (SELECT count(*) FROM screenings s JOIN runs r ON r.id = s.run_id
   WHERE s.prefilter IN ('pass','skipped') AND r.started_at >= :start AND r.started_at < :end) AS candidates,
 (SELECT count(*) FROM screenings s JOIN runs r ON r.id = s.run_id
   WHERE s.screened_in AND r.started_at >= :start AND r.started_at < :end) AS screened_in,
 (SELECT count(*) FROM cards c JOIN runs r ON r.id = c.run_id WHERE r.started_at >= :start AND r.started_at < :end) AS carded,
 (SELECT count(*) FROM cards c JOIN runs r ON r.id = c.run_id
   WHERE c.status IN ('verified','reviewed','stale') AND r.started_at >= :start AND r.started_at < :end) AS verified,
 (SELECT count(*) FROM reviews WHERE created_at >= :start AND created_at < :end) AS reviewed,
 (SELECT count(*) FROM reviews WHERE relevance IN ('yes','partly') AND created_at >= :start AND created_at < :end) AS relevant,
 (SELECT count(*) FROM reviews WHERE deep_read AND created_at >= :start AND created_at < :end) AS deep_read
"""
FUNNEL_STEPS = ["harvested", "candidates", "screened_in", "carded", "verified", "reviewed", "relevant", "deep_read"]

# --- hover help: one dict, the same text on every page ------------------------------------------------

HELP = {
    "harvested": "New paper versions arXiv announced on the most recent announcement day (Mon–Fri) the last Watch run covered. Red at 0 on an announcement day: Watch ran but got nothing.",
    "hwm_days": "Announcement days since the high-water mark last moved forward. The mark only advances when every set harvested cleanly. Red above 2.",
    "failures": "Stage runs that failed in the last 7 days and have not since succeeded on a retry. Red at any.",
    "candidates": "Papers that passed the keyword pre-filter in the last 7 days and were scored by the model. Red outside alerts.candidates_range.",
    "unsupported": "Share of Card fields whose quote Verify could not find, over the Cards Read in the last 7 days. Inferred fields are not counted. Red above alerts.unsupported_rate.",
    "grounding": "Share of Evidence quotes found verbatim on the latest Golden eval run. Red below 98%; that is a hard fail, and the run can't be accepted.",
    "invented": "Numbers in a Card that appear nowhere in the paper: Cards from the last 7 days, plus the latest Golden eval run. Red at any.",
    "golden_diff": "Material changes in the latest Golden eval run against its accepted baseline. Red while the run has any and is not yet accepted.",
    "precision": "Share of your Reviews in the last 14 days rated yes or partly: how often a Screened-in paper was worth Carding. Red below 70%, once there are 20 Reviews.",
    "review_time": "Median time per Review over the last 7 days, from page load to save. Red above alerts.review_minutes.",
    "cost_per_card": "Median cost per Carded paper over the last 7 days: every run tied to the paper, retries included. Red above 2× the week-1 median.",
    "spend": "Spend so far this ISO week (from Monday 00:00 UTC) against budget.weekly_usd. At 100% Read selects nothing until next Monday. Red at 80%.",
    "spark": "One bar per day for the last 7 days (for Golden tiles: one per eval run). Grey bars are weekends.",
    "empty": "Nothing to compute yet. A grey tile is neither green nor red; the M0 exit criterion needs every tile to have shown a value.",
    "funnel": "Counts of what happened in the last 7 days at each step. A sudden narrowing between two steps points at the Stage to inspect.",
    "runslink": "The runs behind this value, in the run list.",
    "secnav": "Jump to a question. Keys: [ and ]",
    "sql": "Show the SQL behind each tile. Key: q",
    "redcount": "Instruments that need action now.",
    "paused": "The weekly spend guardrail is reached: Read selects nothing until Monday.",
    "lastrun": "Time since the last phy daily finished.",
}

# --- seeding -------------------------------------------------------------------------------------------


def ts(d: datetime) -> str:
    return d.strftime("%Y-%m-%d %H:%M:%S")


def fake_card(n_fields: int, unsupported: int) -> str:
    fields = [{"value": "…", "evidence": [], "support": "unsupported" if i < unsupported else "supported"} for i in range(n_fields)]
    return json.dumps({"tldr": "…", "key_results": fields[:5], "assumptions": fields[5:8], "rest": fields[8:], "opinion": {"text": "…"}})


def seed(scenario: str) -> None:
    DB.unlink(missing_ok=True)
    rnd = random.Random(7)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    days = 2 if scenario == "fresh" else 28
    run_id = 0

    def run(stage, when, arxiv=None, status="ok", cost=0.0, error=None):
        nonlocal run_id
        run_id += 1
        con.execute("INSERT INTO runs (id, stage, arxiv_id, status, error, cost_usd, started_at, ended_at) VALUES (?,?,?,?,?,?,?,?)",
                    (run_id, stage, arxiv, status, error, cost, ts(when), ts(when + timedelta(minutes=2))))
        return run_id

    pid = 0
    card_id = 0
    hwm = None
    for k in range(days, -1, -1):
        day = (NOW - timedelta(days=k)).replace(hour=6, minute=0)
        if day > NOW:
            continue
        stuck = scenario == "broken" and k <= 5
        watch_status = "failed" if stuck else "ok"
        run("watch", day, status=watch_status, error="OAI-PMH 503 after 3 attempts" if stuck else None)
        if not stuck:
            hwm = day
        # harvested on announcement days
        n_harv = 0 if day.weekday() >= 5 or stuck else rnd.randint(260, 340)
        filt = run("filter", day + timedelta(minutes=5), cost=0.0)
        n_cand = 0
        for _ in range(n_harv):
            pid += 1
            aid = f"2610.{pid:05d}"
            con.execute("INSERT INTO papers (arxiv_id, latest_version, title, first_seen_at) VALUES (?,?,?,?)", (aid, 1, "…", ts(day)))
            con.execute("INSERT INTO paper_versions (arxiv_id, version, first_seen_datestamp) VALUES (?,?,?)", (aid, 1, day.date().isoformat()))
            pre = "pass" if rnd.random() < 0.17 else "fail"
            score = rnd.random() ** 2.2 if pre == "pass" else None
            if pre == "pass":
                n_cand += 1
            con.execute("INSERT INTO screenings (arxiv_id, version, prefilter, best_score, screened_in, run_id) VALUES (?,?,?,?,?,?)",
                        (aid, 1, pre, score, int(bool(score and score >= 0.5)), filt))
        con.execute("UPDATE runs SET cost_usd = ? WHERE id = ?", (round(n_cand * 0.00015, 4), filt))
        # Read + Verify on the day's top screened-in papers
        picks = con.execute("SELECT arxiv_id FROM screenings WHERE run_id = ? AND screened_in ORDER BY best_score DESC LIMIT 8", (filt,)).fetchall()
        for i, (aid,) in enumerate(picks):
            when = day + timedelta(minutes=10 + i)
            cost = round(rnd.uniform(0.07, 0.13), 3)
            if rnd.random() < 0.05:  # a failed Read, retried later the same morning
                run("read", when, aid, "failed", cost=0.02, error="flatten: \\input not found")
                if scenario == "broken" and k == 1:
                    continue  # unretried
            rid = run("read", when + timedelta(seconds=30), aid, cost=cost)
            run("verify", when + timedelta(seconds=60), aid)
            n_fields = rnd.randint(14, 18)
            uns = rnd.choice([0, 0, 0, 0, 1, 1, 2]) + (rnd.choice([1, 2, 3]) if scenario == "broken" and k <= 6 else 0)
            invented = ["0.42"] if scenario == "broken" and k == 6 and i == 0 else []
            card_id += 1
            status = "reviewed" if k >= 1 else "verified"
            con.execute("INSERT INTO cards (id, arxiv_id, version, card_json, status, unsupported_count, inferred_count, invented_numbers_json, warnings_json, run_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (card_id, aid, 1, fake_card(n_fields, uns), status, uns, rnd.randint(0, 3), json.dumps(invented), "[]", rid))
            if day.weekday() < 5 and k >= 1 and i < 6:
                rel = rnd.choices(["yes", "partly", "no"], [5, 3, 2])[0]
                con.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?)",
                            (card_id, rel, int(rnd.random() < 0.15), rnd.randint(170, 330), None, ts(day + timedelta(days=1, hours=2, minutes=5 * i))))
    if scenario == "broken":
        run("read", NOW - timedelta(hours=1), None, cost=16.9)  # a burst: spend tile red
    con.execute("INSERT INTO state VALUES ('watch.hwm', ?), ('watch.last_success_at', ?)",
                (ts(hwm), ts(hwm + timedelta(minutes=3))))
    if scenario != "fresh":
        for j, back in enumerate([20, 13, 6, 1]):
            last = j == 3
            bad = scenario == "broken" and last
            con.execute("INSERT INTO eval_runs (id, golden_version, split, metrics_json, baseline_id, material_changes, accepted_at, created_at) VALUES (?,?,?,?,?,?,?,?)",
                        (j + 1, 1, "dev", json.dumps({"grounding_rate": 0.957 if bad else 0.995 - 0.003 * j, "invented_numbers": 1 if bad else 0}),
                         j if j else None, 4 if bad else (1 if j else 0), None if bad else ts(NOW - timedelta(days=back - 0.1)), ts(NOW - timedelta(days=back))))
    con.commit()
    con.close()


# --- computing the tiles -------------------------------------------------------------------------------


def q(con, name_or_sql, start=None, end=None):
    sql = QUERIES.get(name_or_sql, name_or_sql)
    p = {"start": ts(start) if start else None, "end": ts(end) if end else None, "now": ts(NOW)}
    names = [k for k in p if f":{k}" in sql]
    cur = con.execute(sql, {k: p[k] for k in names})
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def daily(con, name, n=7):
    out = []
    for k in range(n - 1, -1, -1):
        s = datetime.combine((NOW - timedelta(days=k)).date(), datetime.min.time())
        row = q(con, name, s, s + timedelta(days=1))[0]
        out.append({"v": row["value"] or 0, "weekend": s.weekday() >= 5})
    return out


def tile(key, title, group, value, shown, threshold, red, series=None, empty=None, link=None, sql=None, note=None):
    return dict(key=key, title=title, group=group, value=value, shown=shown, threshold=threshold, empty=empty,
                state="empty" if empty else ("red" if red else "green"), series=series or [], link=link,
                sql=sql or QUERIES.get(key, ""), note=note)


def compute():
    con = sqlite3.connect(DB)
    c = CONFIG
    end = NOW
    w7, w14 = NOW - timedelta(days=7), NOW - timedelta(days=14)
    T = []

    r = q(con, "harvested")
    r = r[0] if r else {"value": None, "label": None}
    T.append(tile("harvested", "Papers harvested per announcement day", "running", r["value"],
                  f"{r['value']}" if r["label"] else "—", "red at 0", r["value"] == 0,
                  daily(con, "harvested_series"), empty=None if r["label"] else "no successful Watch run yet",
                  link="/runs?stage=watch", note=f"announcement day {r['label']}" if r["label"] else None))

    r = q(con, "hwm_days")[0]
    T.append(tile("hwm_days", "Days since the high-water mark advanced", "running", r["value"], f"{r['value']}",
                  f"red above {c['alerts.hwm_days']}", r["value"] > c["alerts.hwm_days"],
                  empty=None if r["label"] else "no mark yet: Watch hasn't completed",
                  link="/runs?stage=watch", note=f"mark at {r['label'][:16]}" if r["label"] else None))

    r = q(con, "failures", w7, end)[0]
    T.append(tile("failures", "Stage failures", "running", r["value"], f"{r['value']}", "red at any", r["value"] > 0,
                  link=f"/runs?ids={r['run_ids']}" if r["run_ids"] else "/runs?status=failed",
                  note="unretried, last 7 days"))

    r = q(con, "candidates", w7, end)[0]
    lo, hi = c["alerts.candidates_range"]
    first_filter = con.execute("SELECT min(started_at) FROM runs WHERE stage='filter'").fetchone()[0]
    young = first_filter and datetime.fromisoformat(first_filter) > w7
    T.append(tile("candidates", "Candidates per week", "funnel", r["value"], f"{r['value']}", f"red outside {lo}–{hi}",
                  not young and not (lo <= r["value"] <= hi), daily(con, "candidates"),
                  link="/runs?stage=filter", note="partial week: not judged yet" if young else "last 7 days"))

    r = q(con, "unsupported", w7, end)[0]
    T.append(tile("unsupported", "Unsupported-field rate", "right", r["value"],
                  f"{r['value']:.1%}" if r["value"] is not None else "—", f"red above {c['alerts.unsupported_rate']:.0%}",
                  (r["value"] or 0) > c["alerts.unsupported_rate"], daily(con, "unsupported"),
                  empty=None if r["n"] else "no verified Cards yet", link="/runs?stage=read&since=7d",
                  note=f"{r['n']} Cards, last 7 days"))

    r = q(con, "grounding")
    r = r[0] if r else None
    T.append(tile("grounding", "Grounding rate (Golden)", "right", r and r["value"],
                  f"{r['value']:.1%}" if r else "—", "red below 98%", bool(r) and r["value"] < c["alerts.grounding_rate"],
                  [{"v": x["value"], "weekend": False} for x in q(con, "grounding_series")],
                  empty=None if r else "no Golden eval run yet: run phy eval", link=f"/eval/{r['eval_id']}" if r else None,
                  note=f"eval run {r['eval_id']}, {r['label'][:10]}" if r else None))

    r = q(con, "invented", w7, end)[0]
    total = r["cards"] + (r["golden"] or 0)
    T.append(tile("invented", "Invented numbers", "right", total,
                  f"{r['cards']} Cards · {r['golden'] if r['golden'] is not None else '–'} Golden", "red at any", total > 0,
                  daily(con, "invented_series"), link=f"/review?card={r['card_ids'].split(',')[0]}" if r["card_ids"] else None,
                  note="last 7 days + latest eval run"))

    r = q(con, "golden_diff")
    r = r[0] if r else None
    if r and r["baseline_id"] is None:
        T.append(tile("golden_diff", "Golden run-to-run diff", "right", None, "no baseline", "red: Material, unaccepted", False,
                      empty="first eval run: accept it to make the baseline", link=f"/eval/{r['eval_id']}"))
    else:
        T.append(tile("golden_diff", "Golden run-to-run diff", "right", r and r["value"],
                      (f"{r['value']} Material · {'accepted' if r['accepted_at'] else 'not accepted'}") if r else "—",
                      "red: Material, unaccepted", bool(r) and r["value"] > 0 and not r["accepted_at"],
                      empty=None if r else "no Golden eval run yet", link=f"/eval/{r['eval_id']}" if r else None,
                      note=f"eval run {r['eval_id']} vs {r['baseline_id']}" if r else None))

    r = q(con, "precision", w14, end)[0]
    enough = r["n"] >= c["alerts.precision_min_reviews"]
    T.append(tile("precision", "Filter precision", "useful", r["value"],
                  f"{r['value']:.0%}" if r["value"] is not None else "—", "red below 70% (≥ 20 Reviews)",
                  enough and r["value"] < c["alerts.precision"], empty=None if r["n"] else "no Reviews yet",
                  link="/review?relevance=no", note=f"{r['n']} Reviews" + ("" if enough else f": judged from {c['alerts.precision_min_reviews']}")))

    r = q(con, "review_time", w7, end)[0]
    T.append(tile("review_time", "Median review time", "useful", r["value"],
                  f"{int(r['value'])}:{int(r['value'] % 1 * 60):02d}" if r["value"] else "—", f"red above {c['alerts.review_minutes']}:00",
                  (r["value"] or 0) > c["alerts.review_minutes"], daily(con, "review_time"),
                  empty=None if r["n"] else "no Reviews yet", note=f"{r['n'] or 0} Reviews, last 7 days"))

    r = q(con, "cost_per_card", w7, end)[0]
    first = q(con, "cost_week1")[0]["first"]
    base = None
    if first:
        f = datetime.fromisoformat(first)
        if f + timedelta(days=7) <= NOW:
            base = q(con, "cost_per_card", f, f + timedelta(days=7))[0]["value"]
    limit = base and base * c["alerts.cost_multiple"]
    T.append(tile("cost_per_card", "Cost per Carded paper", "affordable", r["value"],
                  f"${r['value']:.3f}" if r["value"] else "—",
                  f"red above ${limit:.3f} (2× week 1)" if base else "baseline forming: week 1 not over",
                  bool(base) and (r["value"] or 0) > limit, daily(con, "cost_per_card"),
                  empty=None if r["value"] else "no Carded papers yet", link="/runs?stage=read&since=7d",
                  note=" · ".join(f"{x['stage']} ${x['usd']}" for x in q(con, "spend_by_stage"))))

    r = q(con, "spend")[0]
    b = c["budget.weekly_usd"]
    T.append(tile("spend", "Weekly spend vs guardrail", "affordable", r["value"], f"${r['value']:.2f} / ${b:.0f}",
                  f"red at {c['alerts.spend_fraction']:.0%}", r["value"] >= c["alerts.spend_fraction"] * b,
                  daily(con, "spend_series"), link="/runs?since=week",
                  note=f"{r['value'] / b:.0%} · last week ${r['last_week']:.2f}"))

    funnels = []
    for k in range(4):
        e = NOW - timedelta(days=7 * k)
        funnels.append({"end": e, **q(con, FUNNEL_SQL, e - timedelta(days=7), e)[0]})
    last_daily = con.execute("SELECT max(ended_at) FROM runs WHERE stage='verify' OR stage='watch'").fetchone()[0]
    con.close()
    return T, funnels, last_daily


# --- rendering -----------------------------------------------------------------------------------------

GROUPS = {"running": "Is it running?", "funnel": "Is the funnel shaped right?", "right": "Is it right?",
          "useful": "Is it useful?", "affordable": "Is it affordable?"}
E = html.escape


def spark(series, w=110, h=26, red=False):
    if not series:
        return ""
    m = max((s["v"] or 0) for s in series) or 1
    bw = w / len(series)
    bars = "".join(
        f'<rect x="{i * bw + 1:.1f}" y="{h - max(1, (s["v"] or 0) / m * h):.1f}" width="{bw - 2:.1f}" height="{max(1, (s["v"] or 0) / m * h):.1f}" class="{"we" if s["weekend"] else ("r" if red else "g")}"/>'
        for i, s in enumerate(series))
    return f'<svg class="spark" width="{w}" height="{h}" title="{E(HELP["spark"])}">{bars}</svg>'


def sqlbox(t):
    return f'<pre class="sql">{E(t["sql"].strip())}</pre>' if t["sql"] else ""


def link(t, label="runs →"):
    return f'<a class="runs" href="{E(t["link"])}" title="{E(HELP["runslink"])}">{label}</a>' if t["link"] else ""


def funnel_strip(f):
    steps = []
    prev = None
    for s in FUNNEL_STEPS:
        v = f[s]
        pct = f'<small>{v / prev:.0%}</small>' if prev else ""
        steps.append(f'<div class="fstep"><b>{v}</b><span>{s.replace("_", " ")}</span>{pct}</div>')
        prev = v or None
    return f'<div class="funnel" title="{E(HELP["funnel"])}">{"".join(steps)}</div>'


def variant_a(T, F):
    out = [f'<section id="sec-funnel0" class="wall"><h2>Funnel <small>last 7 days</small></h2>{funnel_strip(F[0])}</section>']
    for g, label in GROUPS.items():
        tiles = "".join(
            f'<div class="tile {t["state"]}" id="tile-{t["key"]}" title="{E(HELP[t["key"]])}"><div class="tt">{E(t["title"])}</div>'
            f'<div class="tv">{E(t["shown"])}</div>{spark(t["series"], red=t["state"] == "red")}'
            f'<div class="tn">{E(t["empty"] or t["note"] or "")}</div><div class="th">{E(t["threshold"])} {link(t)}</div>{sqlbox(t)}</div>'
            for t in T if t["group"] == g)
        out.append(f'<section id="sec-{g}" class="wall"><h2>{label}</h2><div class="tiles">{tiles}</div></section>')
    return "".join(out)


def variant_b(T, F):
    order = {"red": 0, "empty": 1, "green": 2}
    rows = "".join(
        f'<tr class="{t["state"]}" id="sec-{t["group"]}" title="{E(HELP[t["key"]])}"><td><span class="dot"></span></td>'
        f'<td class="q">{E(GROUPS[t["group"]])}</td><td><b>{E(t["title"])}</b><div class="tn">{E(t["empty"] or t["note"] or "")}</div>{sqlbox(t)}</td>'
        f'<td class="tv">{E(t["shown"])}</td><td class="th">{E(t["threshold"])}</td><td>{spark(t["series"], 90, 20, t["state"] == "red")}</td><td>{link(t)}</td></tr>'
        for t in sorted(T, key=lambda t: order[t["state"]]))
    fun = "".join(
        f'<tr><td>{s.replace("_", " ")}</td><td class="num">{F[0][s]}</td>'
        f'<td><div class="hbar" style="width:{(F[0][s] / (F[0]["harvested"] or 1)) ** 0.35 * 100:.0f}%"></div></td>'
        f'<td class="num muted">{(F[0][s] / F[0][FUNNEL_STEPS[i - 1]]) if i and F[0][FUNNEL_STEPS[i - 1]] else 1:.0%}</td></tr>'
        for i, s in enumerate(FUNNEL_STEPS))
    return (f'<div class="ledger"><table class="led"><thead><tr><th></th><th>Question</th><th>Instrument</th><th>Value</th><th>Red when</th><th>7 days</th><th></th></tr></thead><tbody>{rows}</tbody></table>'
            f'<h2 id="sec-funnel0">Funnel <small>last 7 days · bar width on a compressed scale · % of the step before</small></h2><table class="fun" title="{E(HELP["funnel"])}">{fun}</table></div>')


ACTIONS = {"harvested": "Open the Watch run log", "hwm_days": "Check launchd and the last Watch run", "failures": "Open the run viewer",
           "candidates": "Tighten or loosen keywords", "unsupported": "Inspect runs; revise the Read prompt or parser",
           "grounding": "Revert the change", "invented": "Inspect the Card; this is a hard fail on Golden",
           "golden_diff": "Review the diff on /eval/<id> before accepting", "precision": "Add negative keywords or examples",
           "review_time": "Shorten or reorder the Card", "cost_per_card": "Find which Stage grew",
           "spend": "Check the volume; raise the limit deliberately"}


def action_list(T):
    reds = [t for t in T if t["state"] == "red"]
    if reds:
        cards = "".join(
            f'<div class="act" title="{E(HELP[t["key"]])}"><div class="aq">{E(GROUPS[t["group"]])}</div><div class="ah"><b>{E(t["title"])}</b>'
            f'<span class="tv">{E(t["shown"])}</span><span class="th">{E(t["threshold"])}</span></div>'
            f'<div class="tn">{E(t["note"] or "")}</div><div class="ado">→ {E(ACTIONS[t["key"]])} {link(t, "open the runs")}</div>{sqlbox(t)}</div>'
            for t in reds)
        head = f'<h2 id="sec-red">{len(reds)} need action</h2>{cards}'
    else:
        head = '<h2 id="sec-red" class="allgreen">All green. Nothing to do this week.</h2>'
    return head


def variant_c(T, F):
    head = action_list(T)
    chips = "".join(f'<span class="chip {t["state"]}" title="{E(HELP[t["key"]] + (" — " + t["empty"] if t["empty"] else ""))}">{E(t["title"])} <b>{E(t["shown"])}</b></span>'
                    for t in T if t["state"] != "red")
    cols = "".join(f'<th>to {f["end"]:%d %b}</th>' for f in F)
    rows = ""
    for i, s in enumerate(FUNNEL_STEPS):
        cells = ""
        for f in F:
            prev = f[FUNNEL_STEPS[i - 1]] if i else None
            ratio = f[s] / prev if prev else None
            cells += f'<td class="num">{f[s]}{f"<small> {ratio:.0%}</small>" if ratio is not None else ""}</td>'
        rows += f'<tr><td>{s.replace("_", " ")}</td>{cells}</tr>'
    return (f'<div class="triage">{head}<h2 id="sec-ok">The rest</h2><div class="chips">{chips}</div>'
            f'<h2 id="sec-funnel0">Funnel <small>4 weeks, newest left · % of the step before</small></h2>'
            f'<table class="fun4" title="{E(HELP["funnel"])}"><tr><th></th>{cols}</tr>{rows}</table></div>')


def variant_d(T, F):
    reds = [t for t in T if t["state"] == "red"]
    if not reds:
        head = '<h2 id="sec-red" class="allgreen">All green. Nothing to do this week.</h2>'
    else:
        rows = "".join(
            f'<li title="{E(HELP[t["key"]])}"><a href="#tile-{t["key"]}"><b>{E(t["title"])}</b></a> <span class="tv">{E(t["shown"])}</span>'
            f' <span class="ado">→ {E(ACTIONS[t["key"]])}</span> {link(t)}</li>'
            for t in reds)
        head = f'<h2 id="sec-red">{len(reds)} need action</h2><ul class="actions">{rows}</ul>'
    return head + variant_a(T, F)


VARIANTS = {"A": ("Tile wall", variant_a), "B": ("Ledger", variant_b), "C": ("Triage", variant_c),
            "D": ("Tile wall + actions on top", variant_d)}
PILLS = {"A": [("funnel0", "Funnel")] + [(g, l) for g, l in GROUPS.items()],
         "D": [("red", "Needs action"), ("funnel0", "Funnel")] + [(g, l) for g, l in GROUPS.items()],
         "B": [("funnel0", "Funnel")], "C": [("red", "Needs action"), ("ok", "The rest"), ("funnel0", "Funnel")]}

app = FastAPI()
CURRENT = {"scenario": None}


@app.get("/monitor", response_class=HTMLResponse)
def monitor(variant: str = "A", scenario: str = "healthy"):
    if CURRENT["scenario"] != scenario:
        seed(scenario)
        CURRENT["scenario"] = scenario
    T, F, last = compute()
    name, fn = VARIANTS[variant]
    reds = sum(t["state"] == "red" for t in T)
    spend = next(t for t in T if t["key"] == "spend")
    paused = spend["value"] >= CONFIG["budget.weekly_usd"]
    ago = NOW - datetime.fromisoformat(last) if last else None
    pills = "".join(f'<a href="#sec-{k}" title="{E(HELP["secnav"])}">{E(v)}</a>' for k, v in PILLS[variant])
    keys = list(VARIANTS)
    i = keys.index(variant)
    scen = " · ".join(f'<a href="?variant={variant}&scenario={s}" class="{"on" if s == scenario else ""}">{s}</a>' for s in ("healthy", "broken", "fresh"))
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>phy monitor</title><style>{CSS}</style></head>
<body data-variant="{variant}">
<div class="stick"><div class="topbar"><nav><a href="/review">review</a><a class="on">monitor</a><a href="/runs">runs</a></nav>
<div class="paper"><b>Monitoring</b> <span class="title">last 7 days to {NOW:%a %d %b %H:%M} UTC</span></div>
<div class="badges"><span class="badge {"uns" if reds else "ok"}" title="{E(HELP["redcount"])}">{reds} red</span>
{f'<span class="badge uns" title="{E(HELP["paused"])}">Read paused: budget</span>' if paused else ""}</div>
<div class="live" title="{E(HELP["lastrun"])}">{f"daily {int(ago.total_seconds() // 3600)}h ago" if ago else "never run"}</div>
<button class="sqlbtn" title="{E(HELP["sql"])}" onclick="document.body.classList.toggle('showsql')">sql</button></div>
<div class="secnav">{pills}</div></div>
<main>{fn(T, F)}</main>
<div class="switcher"><a href="?variant={keys[i - 1]}&scenario={scenario}">◀</a> <b>{variant}</b> ({name}) <a href="?variant={keys[(i + 1) % len(keys)]}&scenario={scenario}">▶</a>
<span class="hint">scenario: {scen}</span></div>
<script>
document.addEventListener("keydown", e => {{
  if (e.target.closest("input,textarea,[contenteditable]")) return;
  const a = document.querySelectorAll(".switcher > a");
  if (e.key === "ArrowLeft") a[0].click();
  if (e.key === "ArrowRight") a[1].click();
  if (e.key === "q") document.body.classList.toggle("showsql");
  const p = [...document.querySelectorAll(".secnav a")];
  if (e.key === "]" || e.key === "[") {{
    window._s = ((window._s ?? -1) + (e.key === "]" ? 1 : -1) + p.length) % p.length; p[window._s].click();
  }}
}});
</script></body></html>"""


@app.get("/runs", response_class=HTMLResponse)
def runs(request: Request):
    """Stub of the run list the tiles link to: the filter is the query string."""
    p = dict(request.query_params)
    con = sqlite3.connect(DB)
    where, args = [], []
    if "ids" in p:
        ids = [int(x) for x in p["ids"].split(",")]
        where.append(f"id IN ({','.join('?' * len(ids))})")
        args += ids
    for k in ("stage", "status"):
        if k in p:
            where.append(f"{k} = ?")
            args.append(p[k])
    rows = con.execute(f"SELECT id, stage, arxiv_id, status, error, cost_usd, started_at FROM runs {'WHERE ' + ' AND '.join(where) if where else ''} ORDER BY started_at DESC LIMIT 40", args).fetchall()
    body = "".join(f"<tr class='{'red' if r[3] == 'failed' else ''}'>" + "".join(f"<td>{E(str(x if x is not None else ''))}</td>" for x in r) + "</tr>" for r in rows)
    return f"<!doctype html><style>{CSS}</style><div class='ledger'><h2>PROTOTYPE stub: /runs?{E(str(request.query_params))}</h2><table class='led'><tr><th>id</th><th>stage</th><th>paper</th><th>status</th><th>error</th><th>$</th><th>started</th></tr>{body}</table></div>"


CSS = """
:root { --ink:#1d1f23; --muted:#6a6f78; --line:#e3e5e8; --bg:#fff; --soft:#f6f7f9; --red:#d14343; --redbg:#fdeaea; --ok:#2f855a; --okbg:#e8f5ee; --amber:#b7791f; }
* { box-sizing: border-box; } body { margin:0; font:15px/1.5 -apple-system, system-ui, sans-serif; color:var(--ink); background:var(--bg); }
a { color: inherit; } [title] { cursor: help; } a[title] { cursor: pointer; }
.stick { position: sticky; top:0; z-index:10; background:var(--bg); }
.topbar { display:flex; gap:16px; align-items:center; padding:8px 16px; border-bottom:1px solid var(--line); }
.topbar nav a { margin-left:8px; color:var(--muted); text-decoration:none; } .topbar nav a.on { color:var(--ink); font-weight:600; }
.paper { flex:1; min-width:0; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; } .title { color:var(--muted); }
.badges { display:flex; gap:6px; } .badge { font-size:12px; padding:1px 8px; border-radius:10px; background:var(--soft); }
.badge.uns { background:var(--redbg); color:var(--red); font-weight:600; } .badge.ok { background:var(--okbg); color:var(--ok); }
.live { font:600 14px ui-monospace, monospace; } .sqlbtn { font-size:12px; }
.secnav { border-bottom:1px solid var(--line); padding:4px 16px; display:flex; gap:6px; }
.secnav a { font-size:13px; padding:1px 10px; border-radius:10px; background:var(--soft); text-decoration:none; }
main { padding: 8px 16px 120px; max-width: 1200px; margin: 0 auto; }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:20px 0 6px; scroll-margin-top:100px; }
h2 small { text-transform:none; letter-spacing:0; font-weight:400; }
section { scroll-margin-top: 100px; }
.sql { display:none; font-size:11px; background:#111; color:#cfe; padding:6px; border-radius:4px; white-space:pre-wrap; text-align:left; }
body.showsql .sql { display:block; }
.spark rect.g { fill:#9fcfb4; } .spark rect.r { fill:#e59a9a; } .spark rect.we { fill:#e3e5e8; }
.runs { font-size:12px; color:var(--muted); }
.tn { font-size:12px; color:var(--muted); } .th { font-size:12px; color:var(--muted); }
.muted { color:var(--muted); } .num { text-align:right; font-variant-numeric: tabular-nums; }
/* funnel strip */
.funnel { display:flex; gap:2px; } .fstep { flex:1; background:var(--soft); padding:6px 8px; display:flex; flex-direction:column; }
.fstep b { font-size:20px; } .fstep span { font-size:12px; color:var(--muted); } .fstep small { font-size:11px; color:var(--muted); }
/* A */
.tiles { display:grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap:10px; }
.tile { border:1px solid var(--line); border-top:4px solid var(--ok); border-radius:6px; padding:10px; }
.tile.red { border-top-color:var(--red); background:var(--redbg); } .tile.empty { border-top-color:var(--line); background:var(--soft); }
.tile .tt { font-size:13px; color:var(--muted); } .tile .tv { font-size:24px; font-weight:600; }
.tile.red .tv { color:var(--red); } .tile.empty .tv { color:var(--muted); }
/* B */
.led { width:100%; border-collapse:collapse; font-size:14px; } .led td, .led th { padding:6px 8px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; }
.led th { font-size:12px; color:var(--muted); font-weight:500; } .led .q { font-size:12px; color:var(--muted); white-space:nowrap; }
.led .tv { font-weight:600; white-space:nowrap; } .led tr.red { background:var(--redbg); } .led tr.red .tv { color:var(--red); }
.led tr.empty { color:var(--muted); }
.dot { display:inline-block; width:10px; height:10px; border-radius:5px; background:var(--ok); } tr.red .dot { background:var(--red); } tr.empty .dot { background:var(--line); }
.fun td { padding:2px 8px; font-size:14px; } .fun td:first-child { width:110px; color:var(--muted); } .hbar { height:14px; background:#9fb7e0; min-width:2px; } .fun td:nth-child(3) { width:60%; }
/* C */
.act { border:1px solid var(--red); border-left:6px solid var(--red); border-radius:6px; padding:10px 14px; margin:8px 0; background:var(--redbg); }
.act .aq { font-size:12px; color:var(--muted); } .act .ah { display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; }
.act .tv { font-size:20px; font-weight:600; color:var(--red); } .act .ado { margin-top:4px; font-weight:500; }
.allgreen { color:var(--ok); font-size:18px; text-transform:none; letter-spacing:0; }
.chips { display:flex; flex-wrap:wrap; gap:6px; } .chip { font-size:13px; padding:2px 10px; border-radius:12px; background:var(--okbg); color:#215f40; }
.chip.empty { background:var(--soft); color:var(--muted); border:1px dashed var(--line); }
.fun4 { border-collapse:collapse; font-size:14px; } .fun4 td, .fun4 th { padding:3px 12px; border-bottom:1px solid var(--line); }
.fun4 th { font-size:12px; color:var(--muted); font-weight:500; } .fun4 td:first-child { color:var(--muted); } .fun4 small { color:var(--muted); font-size:11px; }
.actions { list-style:none; margin:0; padding:0; border:1px solid var(--red); border-left:6px solid var(--red); border-radius:6px; background:var(--redbg); }
.actions li { padding:5px 12px; border-bottom:1px solid #f3cfcf; } .actions li:last-child { border-bottom:0; }
.actions .tv { color:var(--red); font-weight:600; margin:0 6px; } .actions a { text-decoration:none; } .actions .runs { text-decoration:underline; }
.tile { scroll-margin-top:100px; }
/* PROTOTYPE chrome */
.switcher { position:fixed; bottom:16px; left:50%; transform:translateX(-50%); z-index:50; display:flex; gap:10px; align-items:center;
  background:#111; color:#fff; padding:6px 14px; border-radius:20px; box-shadow:0 4px 16px #0005; font-size:13px; }
.switcher a { text-decoration:none; } .switcher .hint { color:#aaa; } .switcher .hint a.on { color:#fff; font-weight:600; }
"""

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8001)
