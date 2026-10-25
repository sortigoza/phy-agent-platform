"""The Watch Stage (SPEC §7.1): harvest every configured set since the high-water mark.

Each set is listed with `from=<mark>` and no `until`, through to the last page. The mark moves
to the earliest first-page `responseDate` only once every set has completed; a failed set fails
the run and leaves the mark where it was. Upserts are idempotent, so the `from` day being fetched
again, a re-run, or a `--since` window costs nothing but requests.
"""

from collections import Counter
from datetime import UTC, date, datetime, timedelta

import structlog

from phy import db
from phy.arxiv import Arxiv
from phy.ctx import Ctx

log = structlog.get_logger()

HWM = "watch.hwm"
LAST_SUCCESS = "watch.last_success_at"
COUNTED_AS = {
    "new_paper": "new_papers",
    "new_version": "new_versions",
    "metadata_only": "metadata_only",
    "unchanged": "unchanged",
}
COUNTS = ["pages", "records", *COUNTED_AS.values(), "cards_staled"]


def utc_today() -> date:
    return datetime.now(UTC).date()


def run(ctx: Ctx, *, since: date | None = None, reset: bool = False) -> date | None:
    """Harvest and return the mark afterwards. `reset` clears the mark first, so the run
    backfills `watch.backfill_days`; `since` harvests from that day and never moves the mark
    backwards."""
    with structlog.contextvars.bound_contextvars(run_id=ctx.run_id, stage="watch"):
        started_at = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            mark = _harvest(ctx, since=since, reset=reset)
        except Exception as e:
            db.record_run(ctx.db, ctx.run_id, "watch", "failed", started_at, error=str(e))
            raise
        db.record_run(ctx.db, ctx.run_id, "watch", "ok", started_at)
    return mark


def _harvest(ctx: Ctx, *, since: date | None, reset: bool) -> date | None:
    if reset:
        db.delete_state(ctx.db, HWM)
        log.info("watch.mark_reset")
    stored = db.get_state(ctx.db, HWM)
    mark = date.fromisoformat(stored) if stored else None
    from_ = since or mark or utc_today() - timedelta(days=ctx.config.watch.backfill_days)
    log.info("watch.started", from_date=from_.isoformat(), sets=len(ctx.config.watch.sets))
    first_response_dates = []
    with Arxiv(ctx.paths, ctx.config.arxiv) as arxiv:
        for set_spec in ctx.config.watch.sets:
            counts = Counter({key: 0 for key in COUNTS})
            for page in arxiv.list_records(set_spec, from_):
                if counts["pages"] == 0:
                    first_response_dates.append(page.response_date.date())
                counts["pages"] += 1
                counts["records"] += len(page.records)
                for record in page.records:
                    outcome = db.upsert_paper(ctx.db, record)
                    counts[COUNTED_AS[outcome]] += 1
                    if outcome == "new_version":
                        counts["cards_staled"] += db.mark_cards_stale(
                            ctx.db, record.arxiv_id, record.latest_version
                        )
            log.info("watch.set_harvested", set=set_spec, **counts)
    # A `--since` window later than the mark leaves a gap before it, so it cannot move the mark.
    covers_mark = since is None or (mark is not None and since <= mark)
    if covers_mark:
        mark = max(filter(None, [mark, min(first_response_dates, default=None)]), default=None)
        if mark:
            db.set_state(ctx.db, HWM, mark.isoformat())
    db.set_state(ctx.db, LAST_SUCCESS, datetime.now(UTC).isoformat(timespec="seconds"))
    log.info("watch.finished", mark=mark.isoformat() if mark else None, mark_moved=covers_mark)
    return mark
