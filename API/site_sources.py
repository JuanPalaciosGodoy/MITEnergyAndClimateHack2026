"""Public data for EQORE site assessments.

Every table includes source_url, retrieved_at_utc, geography and data_kind.
Raw provider columns are retained alongside the standardized building fields.
"""

import gzip
import hashlib
import json
import logging
import math
import os
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.etree import ElementTree

import fastexcel
import polars as pl
import requests

from ._http import APIError, get_json
from .green_button import GREEN_BUTTON_SAMPLE, read_green_button

logger = logging.getLogger(__name__)

CA_FILES = {
    2024: "https://www.energy.ca.gov/sites/default/files/2025-10/2024_Download_ADA.xlsx",
    2025: "https://www.energy.ca.gov/sites/default/files/2026-09/2025_Download_ADA.xlsx",
}
MA_LAYERS = {
    2024: "https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/2025_Annual_Report_Data/FeatureServer/0",
    2025: "https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/2026_10_28_LBER_Annual_Report_Data/FeatureServer/0",
}
COMSTOCK_RELEASE = "2025/comstock_amy2018_release_3"
COMSTOCK_BUCKET = "https://oedi-data-lake.s3.amazonaws.com"
COMSTOCK_PREFIX = "nrel-pds-building-stock/end-use-load-profiles-for-us-building-stock"
NATIONAL_GRID_SERVICE = (
    "https://systemdataportal.nationalgrid.com/arcgis/rest/services/"
    "MASDP/MASDP_HostingCapacity/MapServer"
)
FOOTPRINT_INDEX = "https://bfppub.blob.core.windows.net/%24web/2026-08-13/dataset-links.csv"
KBTU_PER_KWH = 3.412141633


def _download(session, url, cache_dir, *, refresh=False):
    """Cache complete downloads. Interrupted requests never replace a valid file."""
    directory = Path(cache_dir)
    directory.mkdir(parents=True, exist_ok=True)
    suffix = Path(url.split("?")[0]).suffix
    target = directory / (hashlib.sha256(url.encode()).hexdigest()[:20] + suffix)
    if target.exists() and not refresh:
        logger.debug("Cache hit %s", url)
        return target
    temporary = None
    try:
        logger.debug("Downloading %s", url)
        with session.get(url, stream=True, timeout=(10, 90)) as response:
            if not response.ok:
                raise APIError(f"GET {url} returned HTTP {response.status_code}")
            with NamedTemporaryFile(dir=directory, delete=False) as output:
                temporary = Path(output.name)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    output.write(chunk)
        temporary.replace(target)
        return target
    except requests.RequestException as error:
        raise APIError(f"GET {url} failed ({type(error).__name__})") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _stamp(frame, url, kind, geography, *, path=None):
    """Cached data retains its original download time."""
    retrieved = datetime.now(timezone.utc)
    if path is not None:
        retrieved = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return frame.with_columns(
        source_url=pl.lit(url),
        retrieved_at_utc=pl.lit(retrieved),
        data_kind=pl.lit(kind),
        geography=pl.lit(geography),
    )


def _arcgis(session, layer_url, *, where="1=1", limit=100, page_size=1000):
    """Read ArcGIS pages in object-ID order, preserving WGS84 geometry."""
    metadata = get_json(session, layer_url, {"f": "json"})
    object_id = next(field["name"] for field in metadata["fields"] if field["type"] == "esriFieldTypeOID")
    rows = []
    offset = 0
    while limit is None or offset < limit:
        count = min(page_size, metadata["maxRecordCount"])
        if limit is not None:
            count = min(count, limit - offset)
        page = get_json(session, layer_url + "/query", {
            "f": "json", "where": where, "outFields": "*",
            "outSR": 4326, "returnGeometry": "true",
            "orderByFields": object_id, "resultOffset": offset,
            "resultRecordCount": count,
        })
        features = page["features"]
        rows.extend({
            **feature["attributes"],
            "geometry_esri_json": json.dumps(feature.get("geometry")),
        } for feature in features)
        offset += len(features)
        logger.debug("ArcGIS %s offset=%d", layer_url, offset)
        if not page.get("exceededTransferLimit"):
            break
        if not features:
            raise APIError(f"ArcGIS {layer_url} returned an empty page before completion.")
    # infer_schema_length=None allows columns that are null in the first page.
    return pl.from_dicts(rows, infer_schema_length=None)


class SiteDataClient:
    """Site data sources with a shared HTTP session and a disk download cache."""

    def __init__(self, session=None, cache_dir="data/raw"):
        self.session = session if session is not None else requests.Session()
        self.cache_dir = Path(cache_dir)

    def california_benchmarking(self, year=2025, *, refresh=False):
        """Reported annual data. year is the energy year, not the download year."""
        url = CA_FILES[year]
        path = _download(self.session, url, self.cache_dir, refresh=refresh)
        frame = fastexcel.read_excel(path).load_sheet(0, header_row=2, schema_sample_rows=None).to_polars()
        frame = frame.with_columns(
            building_id=pl.col("Portfolio Manager Property ID").cast(pl.String),
            address=pl.col("Address 1"),
            city=pl.col("City"),
            state=pl.col("State/Province"),
            latitude=pl.col("Latitude").cast(pl.Float64, strict=False),
            longitude=pl.col("Longitude").cast(pl.Float64, strict=False),
            building_type=pl.col("Primary Property Type - Portfolio Manager-Calculated"),
            floor_area_sqft=pl.col("Property GFA - Calculated (Buildings) (ft²)").cast(pl.Float64, strict=False),
            annual_electricity_kwh=pl.col("Electricity Use - Grid Purchase (kBtu)").cast(pl.Float64, strict=False) / KBTU_PER_KWH,
            data_year=pl.lit(year),
        )
        return _stamp(frame, url, "reported", "CA", path=path)

    def massachusetts_lber(self, year=2025, *, where="1=1", limit=100, page_size=1000):
        """Public annual energy disclosures from the official LBER map's layers."""
        url = MA_LAYERS[year]
        frame = _arcgis(self.session, url, where=where, limit=limit, page_size=page_size)
        if frame.is_empty():
            return _stamp(frame, url, "reported", "MA")
        electricity = {
            2024: "Total_Electricity_Use_Purchased_From_Grid__kBtu_",
            2025: "Total_Electricity_Use_Purchased_From_Grid_kBtu",
        }[year]
        frame = frame.with_columns(
            building_id=pl.col("UBID").cast(pl.String),
            address=pl.col("Street_Address"),
            city=pl.col("City"),
            state=pl.lit("MA"),
            latitude=pl.col("Latitude").cast(pl.Float64, strict=False),
            longitude=pl.col("Longitude").cast(pl.Float64, strict=False),
            building_type=pl.col("Property_Type"),
            floor_area_sqft=pl.col("Gross_Floor_Area").cast(pl.Float64),
            annual_electricity_kwh=pl.col(electricity).cast(pl.Float64) / KBTU_PER_KWH,
            data_year=pl.lit(year),
        )
        return _stamp(frame, url, "reported", "MA")


    def green_button(self, source=GREEN_BUTTON_SAMPLE, *, refresh=False):
        """Read a local customer XML export or download a public Green Button file.

        The default is a public test fixture, labeled sample. Customer utility
        access requires their export or authorized download, not an EIA key.
        """
        if str(source).startswith(("https://", "http://")):
            path = _download(self.session, str(source), self.cache_dir, refresh=refresh)
            source_url = str(source)
        else:
            path = Path(source)
            source_url = path.resolve().as_uri()
        kind = "sample" if str(source) == GREEN_BUTTON_SAMPLE else "customer_provided"
        return read_green_button(path, source_url=source_url, data_kind=kind)

    def comstock_metadata(self, state="MA", county="G2500170", *, upgrade=0, release=COMSTOCK_RELEASE, refresh=False):
        """Modeled building characteristics for one NHGIS county (default Middlesex).

        Use bldg_id from this table to request the corresponding profile.
        County IDs have the NHGIS form G2500170, not the five-digit FIPS form.
        """
        key = (
            f"{COMSTOCK_PREFIX}/{release}/metadata_and_annual_results/by_state_and_county/"
            f"basic/parquet/state={state}/county={county}/{state}_{county}_upgrade{upgrade}_basic.parquet"
        )
        url = f"{COMSTOCK_BUCKET}/{key}"
        path = _download(self.session, url, self.cache_dir, refresh=refresh)
        return _stamp(pl.read_parquet(path), url, "modeled", f"{state} {county}", path=path)

    def comstock_profile(self, state="MA", building_id=None, *, upgrade=0, release=COMSTOCK_RELEASE, refresh=False):
        """One modeled building's full year of 15-minute interval energy.

        Omit building_id to select the first available building in that state.
        This is an arbitrary sample, not a match to an actual street address.
        """
        prefix = f"{COMSTOCK_PREFIX}/{release}/timeseries_individual_buildings/by_state/upgrade={upgrade}/state={state}/"
        if building_id is None:
            response = self.session.get(COMSTOCK_BUCKET, params={
                "list-type": 2, "prefix": prefix, "max-keys": 1,
            }, timeout=30)
            response.raise_for_status()
            root = ElementTree.fromstring(response.content)
            key = root.findtext(".//{*}Contents/{*}Key")
            if key is None:
                raise APIError(f"No ComStock profiles found for {state}, upgrade {upgrade}, release {release}.")
            building_id = Path(key).name.split("-")[0]
        url = f"{COMSTOCK_BUCKET}/{prefix}{building_id}-{upgrade}.parquet"
        path = _download(self.session, url, self.cache_dir, refresh=refresh)
        frame = pl.read_parquet(path).with_columns(
            building_id=pl.lit(str(building_id)),
            comstock_release=pl.lit(release),
        )
        return _stamp(frame, url, "modeled", state, path=path)

    def tariffs(self, latitude, longitude, *, sector="Commercial", limit=2, offset=0):
        """Candidate commercial tariffs near a point. DEMO_KEY permits small tests."""
        key = os.getenv("OPENEI_API_KEY") or "DEMO_KEY"
        url = "https://api.openei.org/utility_rates"
        payload = get_json(self.session, url, {
            "version": 8, "format": "json", "api_key": key,
            "lat": latitude, "lon": longitude, "sector": sector,
            "limit": limit, "offset": offset, "detail": "full",
        })
        # Keep the full nested rate definition losslessly for later bill modeling.
        rows = [{
            "label": item.get("label"),
            "utility": item.get("utility"),
            "name": item.get("name"),
            "sector": item.get("sector"),
            "startdate": item.get("startdate"),
            "enddate": item.get("enddate"),
            "rate_json": json.dumps(item),
        } for item in payload["items"]]
        return _stamp(pl.from_dicts(rows), url, "published_tariff", f"{latitude},{longitude}")

    def national_grid_capacity(self, *, layer=0, where="1=1", limit=100, page_size=1000):
        """MA distribution-generation hosting capacity. Values include MW and kV."""
        url = f"{NATIONAL_GRID_SERVICE}/{layer}"
        frame = _arcgis(self.session, url, where=where, limit=limit, page_size=page_size)
        return _stamp(frame, url, "published_grid", "National Grid MA")

    def building_footprints(self, latitude, longitude, *, limit=20, refresh=False):
        """Stream a sample from the Microsoft zoom-9 tile containing a point.

        Samples come from the start of the tile, not the nearest building.
        The tile can span many kilometers. Polygon coordinates are longitude,
        latitude. The complete published feature is retained in feature_geojson.
        """
        path = _download(self.session, FOOTPRINT_INDEX, self.cache_dir, refresh=refresh)
        links = pl.read_csv(path, schema_overrides={"QuadKey": pl.String})
        zoom = 9
        x = int((longitude + 180) / 360 * (1 << zoom))
        sine = math.sin(math.radians(latitude))
        y = int((0.5 - math.log((1 + sine) / (1 - sine)) / (4 * math.pi)) * (1 << zoom))
        quadkey = "".join(str(((x >> bit) & 1) + 2 * ((y >> bit) & 1)) for bit in range(zoom - 1, -1, -1))
        matches = links.filter((pl.col("Location") == "UnitedStates") & (pl.col("QuadKey") == quadkey))
        if matches.is_empty():
            raise APIError(f"Microsoft's index has no UnitedStates tile for quadkey {quadkey}.")
        url = matches["Url"][0]
        rows = []
        try:
            with self.session.get(url, stream=True, timeout=(10, 90)) as response:
                if not response.ok:
                    raise APIError(f"GET {url} returned HTTP {response.status_code}")
                with gzip.GzipFile(fileobj=response.raw) as stream:
                    for line in islice(stream, limit):
                        feature = json.loads(line)
                        rows.append({
                            "quadkey": quadkey,
                            "geometry_type": feature["geometry"]["type"],
                            "feature_geojson": json.dumps(feature),
                        })
        except requests.RequestException as error:
            raise APIError(f"GET {url} failed ({type(error).__name__})") from None
        return _stamp(pl.from_dicts(rows), url, "inferred", f"UnitedStates quadkey {quadkey}")


def save_snapshot(frame, path):
    """Write a Parquet snapshot atomically, including the provenance columns."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=".parquet", delete=False) as output:
        temporary = Path(output.name)
    try:
        frame.write_parquet(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
