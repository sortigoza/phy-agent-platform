"""`phy ui` (SPEC §9): FastAPI with Jinja templates and HTMX, no build step. Reads SQLite and
the Paper files; never takes `phy.lock`.
"""

import sqlite3
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from phy import db
from phy.config import Paths, load_config
from phy.release import release_status
from phy.ui import export, figures, monitor, review, runs
from phy.ui.help import HELP, MONITOR_KEYS, REVIEW_KEYS

HERE = Path(__file__).parent
ARXIV_ID = r"^\d{4}\.\d{4,5}$"
# A Flag target such as `tldr`, `key_results[0]` or `opinion.limitations_flagged[1]`.
FIELD_PATH = r"^[a-z_]+(\[\d+\])?(\.[a-z_]+(\[\d+\])?)?$"
FlagKind = Literal["wrong_value", "quote_doesnt_support", "missing", "should_be_opinion"]


def create_app(paths: Paths, clock: Callable[[], float] = time.time) -> FastAPI:
    """`clock` times a Review, from render to submit."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["help"] = HELP
    templates.env.globals["flag_kinds"] = review.FLAG_KINDS

    def page(request: Request, name: str, **context) -> HTMLResponse:
        """Render a page with what the shared top bar needs."""
        return templates.TemplateResponse(
            request, name, {"release": release_status(paths), **context}
        )

    def next_card(request: Request, saved: dict | None = None) -> HTMLResponse:
        """The `/review` page for the next Card in the queue, timed from now."""
        conn = db.connect(paths.db)
        try:
            queue = db.review_queue(conn)
            flags = db.card_flags(conn, queue[0]["id"]) if queue else []
        finally:
            conn.close()
        if not queue:
            return page(request, "review.html", page="review", view=None, waiting=0, saved=saved)
        v = review.view(paths, queue[0])
        return page(
            request,
            "review.html",
            page="review",
            view=v,
            waiting=len(queue),
            macros=v.macros,
            rendered_at=clock(),
            saved=saved,
            keys=REVIEW_KEYS,
            flags_by_path=_by_path(flags),
        )

    @app.get("/review", response_class=HTMLResponse)
    def review_page(request: Request):
        return next_card(request)

    @app.post("/reviews", response_class=HTMLResponse)
    def save_review(
        request: Request,
        card_id: Annotated[int, Form()],
        rendered_at: Annotated[float, Form()],
        relevance: Annotated[Literal["yes", "partly", "no"], Form()],
        deep_read: Annotated[bool, Form()] = False,
        note: Annotated[str, Form()] = "",
    ):
        """Store the Review, timed from render to now, and render the next Card."""
        seconds = max(round(clock() - rendered_at), 0)
        conn = db.connect(paths.db)
        try:
            card = db.card_for_review(conn, card_id)
            if card is None:
                raise HTTPException(404, f"no card {card_id}")
            if not db.write_review(conn, card_id, relevance, deep_read, seconds, note or None):
                raise HTTPException(409, f"card {card_id} already has a Review")
        finally:
            conn.close()
        saved = {
            "card_id": card_id,
            "paper": f"{card['arxiv_id']}v{card['version']}",
            "relevance": relevance,
            "deep_read": deep_read,
            "seconds": seconds,
        }
        return next_card(request, saved)

    def chips(
        request: Request, conn: sqlite3.Connection, card_id: int, field_path: str
    ) -> HTMLResponse:
        flags = [f for f in db.card_flags(conn, card_id) if f["field_path"] == field_path]
        return templates.TemplateResponse(request, "_flag_chips.html", {"flags": flags})

    def open_card(conn: sqlite3.Connection, card_id: int) -> None:
        """Raise unless the Card exists and has no Review, so its Flags can still change."""
        if db.card_for_review(conn, card_id) is None:
            raise HTTPException(404, f"no card {card_id}")
        if db.get_review(conn, card_id):
            raise HTTPException(409, f"card {card_id} has a Review; its Flags are final")

    @app.post("/flags", response_class=HTMLResponse)
    def add_flag(
        request: Request,
        card_id: Annotated[int, Form()],
        field_path: Annotated[str, Form(pattern=FIELD_PATH)],
        kind: Annotated[FlagKind, Form()],
        note: Annotated[str, Form()] = "",
    ):
        conn = db.connect(paths.db)
        try:
            open_card(conn, card_id)
            db.add_flag(conn, card_id, field_path, kind, note.strip() or None)
            return chips(request, conn, card_id, field_path)
        finally:
            conn.close()

    @app.delete("/flags/{flag_id}", response_class=HTMLResponse)
    def delete_flag(request: Request, flag_id: int):
        conn = db.connect(paths.db)
        try:
            flag = db.get_flag(conn, flag_id)
            if flag is None:
                raise HTTPException(404, f"no flag {flag_id}")
            open_card(conn, flag["card_id"])
            db.delete_flag(conn, flag_id)
            return chips(request, conn, flag["card_id"], flag["field_path"])
        finally:
            conn.close()

    @app.get("/monitor", response_class=HTMLResponse)
    def monitor_page(request: Request):
        now = datetime.fromtimestamp(clock(), UTC)
        config = load_config(paths)
        conn = db.connect(paths.db)
        try:
            tiles = monitor.instruments(conn, config, now)
            funnel = monitor.funnel(conn, now)
        finally:
            conn.close()
        return page(
            request,
            "monitor.html",
            page="monitor",
            now=now,
            tiles=tiles,
            reds=[t for t in tiles if t.state == "red"],
            funnel=funnel,
            questions=monitor.QUESTIONS,
            keys=MONITOR_KEYS,
        )

    @app.get("/runs", response_class=HTMLResponse)
    def runs_page(
        request: Request,
        stage: str | None = None,
        status: runs.Status | None = None,
        ids: str | None = None,
        since: Annotated[str | None, Query(pattern=runs.SINCE)] = None,
    ):
        """`ids` is a comma-separated list of arXiv ids; `since` is `<n>d`, `week` or an ISO
        date or timestamp."""
        try:
            start = runs.since_start(since, datetime.fromtimestamp(clock(), UTC)) if since else None
        except ValueError:
            raise HTTPException(422, f"since: not a date: {since}") from None
        conn = db.connect(paths.db)
        try:
            rows = db.list_runs(
                conn, stage=stage, status=status, arxiv_ids=runs.arxiv_ids(ids), since=start
            )
        finally:
            conn.close()
        others = {k: v for k, v in {"stage": stage, "ids": ids, "since": since}.items() if v}
        return page(
            request,
            "runs.html",
            page="runs",
            runs=[runs.row(r) for r in rows],
            filters=[f"{k}={v}" for k, v in (others | {"status": status}).items() if v],
            pills=runs.status_pills(others, status),
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run_page(request: Request, run_id: str):
        conn = db.connect(paths.db)
        try:
            run = db.get_run(conn, run_id)
        finally:
            conn.close()
        if run is None:
            raise HTTPException(404, f"no run {run_id}")
        return page(request, "run.html", page="runs", run=runs.view(paths, run))

    @app.get("/cards/{card_id}/export.md")
    def export_card(card_id: int):
        """The Card with its Flags and Review, as a Markdown download."""
        conn = db.connect(paths.db)
        try:
            row = db.card_for_review(conn, card_id)
            if row is None:
                raise HTTPException(404, f"no card {card_id}")
            md = export.markdown(
                review.view(paths, row), db.card_flags(conn, card_id), db.get_review(conn, card_id)
            )
        finally:
            conn.close()
        name = f"{row['arxiv_id']}v{row['version']}.md"
        return Response(
            md,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{name}"'},
        )

    @app.get("/figure/{arxiv_id}/{version}/{name:path}")
    def figure(
        arxiv_id: Annotated[str, PathParam(pattern=ARXIV_ID)],
        version: int,
        name: str,
    ):
        found = figures.image(paths, arxiv_id, version, name)
        if found is None:
            return Response(status_code=404)
        data, media_type = found
        return Response(data, media_type=media_type)

    return app


def _by_path(flags: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for f in flags:
        out.setdefault(f["field_path"], []).append(f)
    return out
