"""Run with uv run uvicorn API.server:app --reload --port 8002."""

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .ma_sources import DEFAULT_SOURCES, REFERENCES, SOURCES
from .site_lookup import SCHEMA_VERSION, lookup_site
from .checklist_table import TABLE_COLUMNS, checklist_table

app = FastAPI(
    title="EQORE Massachusetts site data",
    description="Latitude and longitude to public checklist evidence. Unresolved customer and engineering inputs remain explicit.",
    version="1.4.0",
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
    return {"api_version": app.version, "schema_version": SCHEMA_VERSION, "table_columns": TABLE_COLUMNS,
            "automated": SOURCES, "default_sources": DEFAULT_SOURCES, "references": REFERENCES}


@app.get("/site")
def site(
    latitude: float = Query(ge=-90, le=90, description="WGS84 latitude. Choose a point on the facility."),
    longitude: float = Query(ge=-180, le=180, description="WGS84 longitude."),
    sources: str | None = Query(default=None, description="Optional comma-separated automated source IDs. Utilities is always included."),
    refresh: bool = Query(default=False, description="Refresh supporting downloads."),
    download_evidence: bool = Query(default=True, description="Save provider JSON and supporting public files under data/evidence."),
) -> dict:
    """Return public geolocation evidence, provider results and unresolved public fields.

    Independent provider errors yield a partial HTTP 200 response. Invalid
    coordinates/source names and points outside MA land coverage yield 422.
    """
    selected = [name.strip() for name in sources.split(",") if name.strip()] if sources is not None else None
    try:
        return lookup_site(latitude, longitude, sources=selected, refresh=refresh, download_evidence=download_evidence)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.get("/site/table")
def site_table(
    latitude: float = Query(ge=-90, le=90, description="WGS84 latitude."),
    longitude: float = Query(ge=-180, le=180, description="WGS84 longitude."),
    sources: str | None = Query(default=None, description="Optional comma-separated automated source IDs."),
    refresh: bool = Query(default=False, description="Refresh supporting downloads."),
    download_evidence: bool = Query(default=True, description="Download supporting public evidence."),
    include_all: bool = Query(default=False, description="Include workflow inputs and final battery-design fields."),
) -> list[dict]:
    """Dated rows with searched/source coordinates, distance and evidence links."""
    return checklist_table(site(latitude, longitude, sources, refresh, download_evidence), include_all=include_all).to_dicts()


@app.get("/evidence/{file_path:path}", response_class=FileResponse)
def evidence_file(file_path: str):
    """Serve only public evidence downloaded under this backend's evidence folder."""
    root = Path("data/evidence").resolve()
    path = (root / file_path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Evidence file not found")
    return FileResponse(path)
