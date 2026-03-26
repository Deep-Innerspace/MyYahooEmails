"""FastAPI application factory for the MyYahooEmails web dashboard."""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.web.routes import router

BASE_DIR = Path(__file__).parent


def create_app() -> FastAPI:
    app = FastAPI(title="MyYahooEmails Dashboard", docs_url=None, redoc_url=None)

    # Static files
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

    # Include all routes
    app.include_router(router)

    return app


app = create_app()
