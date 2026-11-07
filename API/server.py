"""Run with uv run --env-file .env uvicorn API.server:app --reload --port 8001."""

import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .ma_sources import REFERENCES, SOURCES
from .site_lookup import lookup_site
from .checklist_table import checklist_table

app = FastAPI(
    title="EQORE Massachusetts site data",
    description="Latitude and longitude to public checklist evidence. Unresolved customer and engineering inputs remain explicit.",
    version="1.0.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    """Process health. Does not call upstream providers."""
    return {"status": "ok"}


@app.get("/sources")
def sources():
    """Automated providers and references requiring manual or authorized access."""
    return {"automated": SOURCES, "references": REFERENCES}


@app.get("/site")
def site(
    latitude: float = Query(ge=-90, le=90, description="WGS84 latitude. Choose a point on the facility."),
    longitude: float = Query(ge=-180, le=180, description="WGS84 longitude."),
    sources: str | None = Query(default=None, description="Optional comma-separated automated source IDs. Utilities is always included."),
    refresh: bool = Query(default=False, description="Download a fresh MassCEC workbook instead of using its cached file."),
) -> dict:
    """Return all twelve checklist categories, provider results and missing inputs.

    Independent provider errors yield a partial HTTP 200 response. Invalid
    coordinates/source names and points outside MA land coverage yield 422.
    """
    selected = [name.strip() for name in sources.split(",") if name.strip()] if sources is not None else None
    try:
        return lookup_site(latitude, longitude, sources=selected, refresh=refresh)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.get("/site/table")
def site_table(
    latitude: float = Query(ge=-90, le=90, description="WGS84 latitude."),
    longitude: float = Query(ge=-180, le=180, description="WGS84 longitude."),
    sources: str | None = Query(default=None, description="Optional comma-separated automated source IDs."),
    refresh: bool = Query(default=False, description="Download a fresh MassCEC workbook."),
) -> list[dict]:
    """Exactly four columns. Missing values stay null and source errors get *.error rows."""
    return checklist_table(site(latitude, longitude, sources, refresh)).to_dicts()
