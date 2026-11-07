"""Small coordinate queries against public Massachusetts data services.

Provider attributes are kept intact. Spatial matches identify published
features, not a customer's meter or an engineer-approved installation.
"""

import json
import re
from pathlib import Path
from urllib.parse import urlencode

import requests

from ._http import get_json
from . import public_gis, public_records, public_energy
from .public_utils import (
    page_links,
    public_file,
    inspect_pdf,
)

KBTU_PER_KWH = 3.412141633
LBER_2025 = "https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/2026_10_28_LBER_Annual_Report_Data/FeatureServer/0"

SOURCES = {
    "utilities": {
        "title": "MassGIS — electricity providers by municipality",
        "url": "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/ElectricityProviders/MapServer/0",
        "description": "Municipality and its published electric providers. Service area is public context; actual facility service is not established.",
        "data_kind": "published_utility_territory",
        "match_method": "municipality_containing_point",
        "fields": "TOWN,TOWN_ID,ELEC",
        "geometry": False,
    },
    "parcels": {
        "title": "MassGIS — Massachusetts assessor parcels",
        "url": "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/Massachusetts_Property_Tax_Parcels/FeatureServer/0",
        "description": "Containing assessor parcels, owner, address, use, area, zoning and recorded deed references.",
        "data_kind": "reported_assessor",
        "match_method": "point_intersection",
        "geometry": True,
    },
    "buildings": {
        "title": "MassGIS — building structures and roof outlines",
        "url": "https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/Building_Structures/FeatureServer/0",
        "description": "Mapped roof/building outline intersecting the point. Area is not gross floor area or usable battery space.",
        "data_kind": "published_geometry",
        "match_method": "point_intersection",
        "geometry": True,
    },
    "lber": {
        "title": "Massachusetts DOER — multi-year building energy disclosures",
        "url": LBER_2025,
        "description": "Paginated 2024 and 2025 annual disclosures within 250 m (up to 1,000 per year). Candidates require a building/reporting-boundary match.",
        "data_kind": "reported",
        "match_method": "within_250m_candidate",
        "radius_m": 250,
        "geometry": True,
    },
    "flood": {
        "title": "FEMA — National Flood Hazard Layer",
        "url": "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28",
        "description": "FEMA flood-zone polygons at the point. No returned feature does not establish absence of flood risk.",
        "data_kind": "published_hazard",
        "match_method": "point_intersection",
        "fields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF,DFIRM_ID",
        "geometry": False,
    },
    "permits": {
        "title": "City of Cambridge — Permit Finder",
        "url": "https://data.cambridgema.gov/resource/3wsm-e5jx.json",
        "description": "Up to ten nearby Cambridge permits within 250 m, retained as candidates rather than confirmed site records.",
        "data_kind": "published_permit_candidates",
        "match_method": "within_250m_candidate",
    },
    "electrical_permits": {
        "title": "City of Cambridge — detailed electrical permits",
        "url": "https://data.cambridgema.gov/resource/hvtc-3ab9.json",
        "description": "Up to five nearby electrical permits with reported service/equipment fields. These describe permitted work, not verified present equipment.",
        "data_kind": "published_electrical_permit_candidates",
        "match_method": "within_250m_candidate",
    },
    "solar_permits": {
        "title": "City of Cambridge — solar installation permits",
        "url": "https://data.cambridgema.gov/resource/whpw-w55x.json",
        "description": "Up to five solar permit candidates within 250 m. No returned permit does not establish absence of solar or batteries.",
        "data_kind": "published_solar_permit_candidates",
        "match_method": "within_250m_candidate",
    },
    "public_resources": {
        "title": "Massachusetts and municipal permitting references",
        "url": "https://www.mass.gov/regulations/780-CMR-tenth-edition-table-of-contents",
        "description": "Official state reference pages and available municipal building/fire contacts. Project applicability and jurisdiction require confirmation.",
        "data_kind": "public_reference",
        "match_method": "municipal_or_state_reference",
    },
    "elevation": {
        "title": "Open-Meteo — terrain elevation",
        "url": "https://api.open-meteo.com/v1/elevation",
        "description": "Terrain elevation in meters. It does not establish finished floor, pad elevation or ground conditions.",
        "data_kind": "modeled_terrain",
        "match_method": "coordinate_sample",
    },
}

SOURCES.update(
    {
        name: {
            "title": title,
            "url": url,
            "description": description,
            "data_kind": kind,
            "match_method": method,
        }
        for name, title, url, description, kind, method in [
            (
                "assessor_records",
                "Municipal public assessor cards",
                "https://www.mass.gov/info-details/massachusetts-interactive-property-map",
                "Address/parcel-based municipal records, photos and sketches; supported municipal adapters report blocked access explicitly.",
                "reported_assessor_card",
                "parcel_address_candidate",
            ),
            (
                "municipal_archives",
                "Municipal public archive searches",
                "https://portal.laserfiche.com/Portal/Search.aspx?repo=r-65c20b5e",
                "Address-based public search for Holliston, Newton and Northampton; no login or challenges bypassed.",
                "public_archive_candidates",
                "address_search_candidate",
            ),
            (
                "land_records",
                "MassGIS registry district and public recorded-document discovery",
                public_records.REGISTRY_ZIP,
                "Find containing registry district, retain parcel book/page references and attempt its public record route.",
                "public_registry",
                "district_containing_point",
            ),
            (
                "lidar",
                "MassGIS lidar terrain",
                public_gis.LIDAR,
                "Requested point and parcel-envelope grid samples, with a parcel-envelope raster.",
                "lidar_terrain",
                "lidar_sample",
            ),
            (
                "wetlands",
                "MassDEP wetland areas",
                public_gis.LAYERS["wetlands"],
                "Published wetlands intersecting the containing parcel, or the point if parcel matching is ambiguous.",
                "public_environmental_screen",
                "parcel_intersection",
            ),
            (
                "environmental",
                "MassDEP Tier Classified Chapter 21E sites",
                public_gis.LAYERS["environmental"],
                "Published subset of classified contamination sites within 250m of parcel/point.",
                "public_environmental_screen",
                "parcel_buffer_candidate",
            ),
            (
                "activity_use_limits",
                "MassDEP Activity and Use Limitation sites",
                public_gis.LAYERS["activity_use_limits"],
                "Published activity/use limitations near the parcel; absence is not environmental clearance.",
                "public_environmental_screen",
                "parcel_buffer_candidate",
            ),
            (
                "protected_habitat",
                "MassGIS NHESP priority habitat",
                public_gis.LAYERS["protected_habitat"],
                "Published habitat intersections as geographic context only.",
                "public_environmental_screen",
                "parcel_intersection",
            ),
            (
                "masscec",
                "MassCEC public PTS solar report",
                public_energy.PTS_PAGE,
                "All useful public report attributes as municipal context; no street-level assignment.",
                "public_municipal_solar_context",
                "municipality_context",
            ),
            (
                "tariffs",
                "Utility-published tariff candidates",
                public_energy.RATE_DIRECTORY,
                "Retrieve official utility schedule PDFs and quoted rate-component mentions; no account data.",
                "public_tariff_components",
                "utility_area_schedule_candidate",
            ),
        ]
    }
)
DEPENDENT_SOURCES = {
    "assessor_records",
    "municipal_archives",
    "land_records",
    "lidar",
    "wetlands",
    "environmental",
    "activity_use_limits",
    "protected_habitat",
    "masscec",
    "tariffs",
}

DEFAULT_SOURCES = list(SOURCES)

# These sources need a human/site-specific document selection, not another
# point query. They are returned separately with honest access statuses.
REFERENCES = {
    "land_records": {
        "status": "manual_lookup",
        "url": "https://www.mass.gov/news/finding-your-property-records",
        "description": "The land_records adapter resolves the registry district and recorded references, attempts public document discovery and reports blocked image access explicitly.",
    },
    "permits": {
        "status": "manual_lookup",
        "url": None,
        "description": "Municipal portals vary. Search the returned address/parcel for plans and later alterations. Cambridge permits and exposed public files can be retrieved as candidates; archived/as-built plans still require confirmation.",
    },
    "tariff_documents": {
        "status": "reference_only",
        "url": "https://www.mass.gov/info-details/massachusetts-electric-rates-and-tariffs",
        "description": "Official tariff directory. Published candidate schedules and effective dates are retrieved by the tariffs adapter; applicability is not inferred.",
    },
    "requirements": {
        "status": "reference_only",
        "url": "https://www.mass.gov/regulations/780-CMR-tenth-edition-table-of-contents",
        "description": "Identify current building, fire, electrical and municipal submission requirements. This API performs no code-compliance review.",
        "additional_urls": [
            "https://www.mass.gov/info-details/massachusetts-fire-code",
            "https://www.mass.gov/info-details/massachusetts-electrical-code",
        ],
    },
}

MUNICIPAL_PORTALS = {
    "HOLLISTON": "https://www.townofholliston.us/187/Building",
    "NEWTON": "https://newtonma.portal.opengov.com/",
    "NORTHAMPTON": "https://northamptonma.portal.opengov.com/",
    "CAMBRIDGE": "https://www.cambridgema.gov/en/iwantto/applyforabuildingpermit",
    "BOSTON": "https://www.boston.gov/departments/inspectional-services",
}


STATE_RESOURCES = [
    {
        "field": "applicable_requirements",
        "title": "Massachusetts building-code reference — review applicability",
        "url": REFERENCES["requirements"]["url"],
    },
    {
        "field": "applicable_requirements",
        "title": "Massachusetts fire-code reference — review applicability",
        "url": REFERENCES["requirements"]["additional_urls"][0],
    },
    {
        "field": "applicable_requirements",
        "title": "Massachusetts electrical-code reference — review applicability",
        "url": REFERENCES["requirements"]["additional_urls"][1],
    },
    {
        "field": "applicable_requirements",
        "title": "MassDEP — public health, safety and environmental battery-storage guidance",
        "url": "https://www.mass.gov/doc/guidance-on-public-health-safety-and-environmental-impacts-of-electric-battery-storage-and-electric-vehicle-chargers/download",
        "document": True,
    },
]
MUNICIPAL_RESOURCES = {
    "CAMBRIDGE": [
        {
            "field": "building_ahj",
            "title": "Cambridge Inspectional Services — municipal contact; confirm project jurisdiction",
            "url": "https://www.cambridgema.gov/departments/inspectionalservices",
        },
        {
            "field": "fire_ahj",
            "title": "Cambridge Fire Prevention Bureau — municipal contact; confirm project jurisdiction",
            "url": "https://www.cambridgema.gov/cfd/programsandservices/firepreventionbureau",
        },
    ],
}
MUNICIPAL_RESOURCES.update(
    {
        "HOLLISTON": [
            {
                "field": "building_ahj",
                "title": "Holliston Building — published department responsibilities",
                "url": "https://www.townofholliston.us/187/Building",
            },
            {
                "field": "fire_ahj",
                "title": "Holliston Fire — published inspections and code enforcement",
                "url": "https://www.hollistonfire.com/InspCode.htm",
            },
            {
                "field": "applicable_requirements",
                "title": "Holliston commercial/site-plan submission forms",
                "url": "https://www.townofholliston.us/387/Planning-Board-Application-Forms-Inclusi",
            },
            {
                "field": "applicable_requirements",
                "title": "Holliston published permitting guide (2023)",
                "url": "https://www.townofholliston.us/DocumentCenter/View/131/2023-Permitting-Guide-PDF",
                "document": True,
            },
        ],
        "NEWTON": [
            {
                "field": "building_ahj",
                "title": "Newton Inspectional Services — published enforcement responsibilities",
                "url": "https://www.newtonma.gov/government/inspectional-services",
            },
            {
                "field": "fire_ahj",
                "title": "Newton Fire Prevention — public forms and applications",
                "url": "https://www.newtonma.gov/government/fire/fire-prevention/forms-and-applications",
            },
        ],
        "NORTHAMPTON": [
            {
                "field": "building_ahj",
                "title": "Northampton published permits and codes — zoning/building submission process",
                "url": "https://www.northamptonma.gov/938/Permits-Codes",
            },
            {
                "field": "applicable_requirements",
                "title": "Northampton published permit and department responsibility matrix",
                "url": "https://www.northamptonma.gov/DocumentCenter/View/17794/Permits-and-Licenses-for-the-City-of-Northampton",
                "document": True,
            },
        ],
    }
)


def query_point(session, source, latitude, longitude):
    """Bounded ArcGIS point queries, with all geometries returned in WGS84.

    A short list of candidates is intentional. truncated is exposed rather
    than silently claiming the complete set was retrieved.
    """
    config = SOURCES[source]
    params = {
        "f": "json",
        "where": "1=1",
        "outFields": config.get("fields", "*"),
        "geometry": json.dumps(
            {"x": longitude, "y": latitude, "spatialReference": {"wkid": 4326}}
        ),
        "geometryType": "esriGeometryPoint",
        "inSR": 4326,
        "outSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
        "resultRecordCount": 5,
        "returnGeometry": str(config["geometry"]).lower(),
    }
    if source in ("parcels", "buildings"):
        params["returnCentroid"] = "true"
    if config.get("radius_m"):
        params.update(distance=config["radius_m"], units="esriSRUnit_Meter")
    payload = get_json(session, config["url"] + "/query", params)
    return {
        "records": [
            {
                **feature["attributes"],
                **(
                    {"geometry": feature["geometry"]} if feature.get("geometry") else {}
                ),
                **(
                    {"centroid": feature["centroid"]} if feature.get("centroid") else {}
                ),
            }
            for feature in payload["features"]
        ],
        "truncated": bool(payload.get("exceededTransferLimit")),
        "query": params,
    }


def fetch_source(
    source,
    latitude,
    longitude,
    *,
    municipality=None,
    context=None,
    cache_dir="data/public_cache",
    refresh=False,
):
    """One provider per call, using its own session so calls can run concurrently."""
    context = context or {}
    with requests.Session() as session:
        if source in public_gis.LAYERS:
            return public_gis.screen(session, source, latitude, longitude, context)
        if source == "lidar":
            return public_gis.lidar(session, latitude, longitude, context)
        if source == "assessor_records":
            return public_records.assessor(
                session, municipality, context, cache_dir, refresh
            )
        if source == "municipal_archives":
            return public_records.municipal_archive(
                session, municipality, context, cache_dir
            )
        if source == "land_records":
            return public_records.land_records(
                session, latitude, longitude, context, cache_dir, refresh
            )
        if source == "masscec":
            return public_energy.masscec(
                session, municipality, context, cache_dir, refresh
            )
        if source == "tariffs":
            return public_energy.tariffs(
                session, municipality, context, cache_dir, refresh
            )
        if source == "public_resources":
            records, errors, artifacts, requirements = [], [], [], []
            for resource in [
                *STATE_RESOURCES,
                *MUNICIPAL_RESOURCES.get(municipality, []),
            ]:
                try:
                    asset = public_file(
                        session,
                        resource["url"],
                        resource["title"],
                        cache_dir,
                        refresh,
                        kind="document"
                        if resource.get("document")
                        else "reference_page",
                    )
                    artifacts.append(asset)
                    records.append(
                        {
                            **resource,
                            "source_title": resource["title"],
                            "retrieved_at_utc": asset["fetched_at_utc"],
                            "match_method": "state_reference"
                            if resource["field"] == "applicable_requirements"
                            else "municipal_reference",
                        }
                    )
                    if (
                        resource.get("document")
                        and asset["content_type"] == "application/pdf"
                    ):
                        parsed = inspect_pdf(asset, role="requirements")
                        asset.update(
                            text_file=parsed["text_file"],
                            page_count=parsed["page_count"],
                        )
                        requirements.extend(parsed["records"])
                    elif asset["content_type"] == "text/html":
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(
                            Path(asset["local_file"]).read_bytes(), "html.parser"
                        )
                        related = [
                            a
                            for a in page_links(soup, resource["url"])
                            if re.search(
                                r"commercial|site plan.*checklist|submission.*checklist|battery|energy storage",
                                a["title"],
                                re.I,
                            )
                            and re.search(
                                r"\.pdf|DocumentCenter/View|showpublisheddocument",
                                a["url"],
                                re.I,
                            )
                        ]
                        for link in related[:3]:
                            try:
                                doc = public_file(
                                    session,
                                    link["url"],
                                    link["title"],
                                    cache_dir,
                                    refresh,
                                )
                                artifacts.append(doc)
                                if doc["content_type"] == "application/pdf":
                                    parsed = inspect_pdf(doc, role="requirements")
                                    doc.update(
                                        text_file=parsed["text_file"],
                                        page_count=parsed["page_count"],
                                    )
                                    requirements.extend(parsed["records"])
                            except Exception as error:
                                errors.append({"url": link["url"], "error": str(error)})
                        for node in soup.select(
                            "main p, main li, article p, article li"
                        ):
                            text = node.get_text(" ", strip=True)
                            if len(text) < 650 and re.search(
                                r"(?:permit|plan|application|drawing).{0,70}(?:required|must|shall|submit)",
                                text,
                                re.I,
                            ):
                                requirements.append(
                                    {
                                        "requirement_excerpt": text,
                                        "url": resource["url"],
                                        "source_title": resource["title"],
                                        "applicability": "municipal/state published submission guidance; project applicability unverified",
                                    }
                                )
                except Exception as error:
                    errors.append(
                        {
                            "url": resource["url"],
                            "error": f"{type(error).__name__}: {error}",
                        }
                    )
            return {
                "records": records,
                "requirements": requirements,
                "artifacts": artifacts,
                "resource_errors": errors,
                "truncated": False,
            }
        if source in ("permits", "electrical_permits", "solar_permits"):
            if municipality != "CAMBRIDGE":
                return {
                    "status": "blocked",
                    "records": [],
                    "truncated": False,
                    "detail": "Automated permit search currently covers Cambridge. Use the municipal reference portal elsewhere.",
                }
            where = f"within_circle(coordinates, {latitude}, {longitude}, 250)"
            if source == "electrical_permits":
                # Find useful service/equipment records rather than letting recent
                # low-voltage data-wiring jobs displace all older service evidence.
                where += " AND (volts_existing_service IS NOT NULL OR volts_new_service IS NOT NULL OR amps_existing_service IS NOT NULL OR amps_new_service IS NOT NULL OR generators IS NOT NULL OR photovoltaic_panels IS NOT NULL)"
            limit = 10 if source == "permits" else 5
            params = {
                "$where": where,
                "$order": "issue_date DESC, id DESC",
                "$limit": limit,
            }
            records = get_json(session, SOURCES[source]["url"], params)
            if source != "permits":
                for record in records:
                    record["specific_url"] = {
                        "url": SOURCES[source]["url"]
                        + "?"
                        + urlencode(
                            {"$where": "id='" + record["id"].replace("'", "''") + "'"}
                        )
                    }
            return {
                "records": records,
                "truncated": len(records) == limit,
                "query": params,
            }
        if source == "lber":
            records, queries, errors = [], [], []
            truncated = False
            for year, url in [
                (2025, LBER_2025),
                (
                    2024,
                    "https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services/2025_Annual_Report_Data/FeatureServer/0",
                ),
            ]:
                params = {
                    "f": "json",
                    "where": "1=1",
                    "outFields": "*",
                    "geometry": json.dumps(
                        {
                            "x": longitude,
                            "y": latitude,
                            "spatialReference": {"wkid": 4326},
                        }
                    ),
                    "geometryType": "esriGeometryPoint",
                    "inSR": 4326,
                    "outSR": 4326,
                    "distance": 250,
                    "units": "esriSRUnit_Meter",
                    "returnGeometry": "true",
                    "resultRecordCount": 100,
                    "orderByFields": "FID ASC",
                }
                try:
                    for offset in range(0, 1000, 100):
                        params["resultOffset"] = offset
                        payload = get_json(session, url + "/query", params)
                        query_url = url + "/query?" + urlencode(params)
                        queries.append(query_url)
                        features = payload.get("features", [])
                        for f in features:
                            r = {
                                **f["attributes"],
                                "geometry": f.get("geometry", {}),
                                "data_year": year,
                                "_source_url": query_url,
                            }
                            value = r.get(
                                "Total_Electricity_Use_Purchased_From_Grid_kBtu"
                            )
                            try:
                                kwh = (
                                    float(value) / KBTU_PER_KWH
                                    if value is not None
                                    else None
                                )
                            except (TypeError, ValueError):
                                kwh = None
                            r.update(
                                building_id=r.get("UBID"),
                                address=r.get("Street_Address"),
                                city=r.get("City"),
                                floor_area_sqft=r.get("Gross_Floor_Area"),
                                annual_electricity_kwh=kwh,
                            )
                            records.append(r)
                        if not payload.get("exceededTransferLimit"):
                            break
                        if offset == 900:
                            truncated = True
                except Exception as error:
                    errors.append({"year": year, "error": str(error)})
            return {
                "records": records,
                "queries": queries,
                "document_errors": errors,
                "truncated": truncated,
                "years": [2024, 2025],
            }
        if source != "elevation":
            result = query_point(session, source, latitude, longitude)
            return result
        if source == "elevation":
            payload = get_json(
                session,
                SOURCES[source]["url"],
                {"latitude": latitude, "longitude": longitude},
            )
            return {
                "records": [{"elevation_m": payload["elevation"][0]}],
                "truncated": False,
                "query": {"latitude": latitude, "longitude": longitude},
            }
