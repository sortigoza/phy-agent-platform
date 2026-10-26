"""`phy ui` (SPEC §9): FastAPI with Jinja templates and HTMX, no build step. Reads SQLite and
the Paper files; never takes `phy.lock`.
"""

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Request
from fastapi import Path as PathParam
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from phy import db
from phy.config import Paths
from phy.release import release_status
from phy.ui import figures, review
from phy.ui.help import HELP

HERE = Path(__file__).parent
ARXIV_ID = r"^\d{4}\.\d{4,5}$"


def create_app(paths: Paths) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.globals["help"] = HELP

    def page(request: Request, name: str, **context) -> HTMLResponse:
        """Render a page with what the shared top bar needs."""
        return templates.TemplateResponse(
            request, name, {"release": release_status(paths), **context}
        )

    @app.get("/review", response_class=HTMLResponse)
    def review_page(request: Request):
        conn = db.connect(paths.db)
        try:
            queue = db.review_queue(conn)
        finally:
            conn.close()
        if not queue:
            return page(request, "review.html", page="review", view=None, waiting=0)
        v = review.view(paths, queue[0])
        return page(
            request,
            "review.html",
            page="review",
            view=v,
            waiting=len(queue),
            macros=v.macros,
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
