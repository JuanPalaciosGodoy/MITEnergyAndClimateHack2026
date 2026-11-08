"""Live public data for Option 1 site intake only."""

import json
import re
from urllib.parse import urlencode
import requests

from ._http import get_json
from .discovery import LBER_CATALOG, lber_datasets
from . import public_records, public_energy
from .scope import intake_record
from .public_permits import attleboro_permits

KBTU_PER_KWH = 3.412141633

SOURCES = {
    "utilities": {
        "title": "MassGIS — electricity providers by municipality",
        "url": "https://arcgisserver.digital.mass.gov/arcgisserver/rest/services/AGOL/ElectricityProviders/MapServer/0",
        "description": "Municipality and its published electric providers. Service area is "
        "public context; actual facility service is not established.",
        "data_kind": "published_utility_territory",
        "match_method": "municipality_containing_point",
        "fields": "TOWN,TOWN_ID,ELEC",
        "geometry": False,
        "coverage": {"region": "Massachusetts", "scope": "statewide public source"},
    },
    "parcels": {
        "title": "MassGIS — Massachusetts assessor parcels",
        "url": "https://services1.arcgis.com/hGdibHYSPO59RG1h/arcgis/rest/services/Massachusetts_Property_Tax_Parcels/FeatureServer/0",
        "description": "Published parcel identity, ownership, use, dimensions, physical attributes "
        "and recorded-plan references.",
        "data_kind": "reported_assessor",
        "match_method": "point_intersection",
        "geometry": True,
        "coverage": {"region": "Massachusetts", "scope": "statewide public source"},
        "fields": "OBJECTID,LOC_ID,MAP_PAR_ID,PROP_ID,PLAN_ID,REG_ID,TOWN_ID,SITE_ADDR,CITY,ZIP,OWNER1,USE_CODE,USE_DESC,ZONING,BLD_AREA,LOT_SIZE,LOT_UNITS,YEAR_BUILT,STORIES,STYLE,UNITS,LS_BOOK,LS_PAGE,FY,LAST_EDIT",
    },
    "buildings": {
        "title": "MassGIS — building structures and roof outlines",
        "url": "https://services1.arcgis.com/hGdibHYSPO59RG1h/ArcGIS/rest/services/Building_Structures/FeatureServer/0",
        "description": "Mapped roof/building outline intersecting the point. Area is not gross "
        "floor area or usable battery space.",
        "data_kind": "published_geometry",
        "match_method": "point_intersection",
        "geometry": True,
        "coverage": {"region": "Massachusetts", "scope": "statewide public source"},
        "fields": "OBJECTID,STRUCT_ID,AREA_SQ_FT,SOURCEDATE",
    },
    "lber": {
        "title": "Massachusetts DOER — multi-year building energy disclosures",
        "url": "https://services1.arcgis.com/7iJyYTjCtKsZS1LR/arcgis/rest/services",
        "description": "Nearby annual electricity and onsite electrical generation disclosures with "
        "property/reporting-boundary metadata; no fuels, EUI or emissions fields.",
        "data_kind": "reported",
        "match_method": "within_250m_candidate",
        "radius_m": 250,
        "geometry": True,
        "coverage": {"region": "Massachusetts", "scope": "statewide public source"},
    },
    "permits": {
        "title": "Municipal public permit history",
        "url": "https://data.cambridgema.gov/resource/3wsm-e5jx.json",
        "description": "Cambridge nearby permit candidates within 250 m; Attleboro anonymous "
        "address search and public plan attachments. Historical work does not establish current equipment.",
        "data_kind": "published_permit_candidates",
        "match_method": "within_250m_candidate",
        "coverage": {
            "region": "Massachusetts",
            "scope": "municipal adapter",
            "municipalities": ["CAMBRIDGE", "ATTLEBORO"],
        },
    },
    "electrical_permits": {
        "title": "City of Cambridge — detailed electrical permits",
        "url": "https://data.cambridgema.gov/resource/hvtc-3ab9.json",
        "description": "Up to five nearby electrical permits with reported "
        "service/equipment fields. These describe permitted work, not "
        "verified present equipment.",
        "data_kind": "published_electrical_permit_candidates",
        "match_method": "within_250m_candidate",
        "coverage": {
            "region": "Massachusetts",
            "scope": "municipal adapter",
            "municipalities": ["CAMBRIDGE"],
        },
    },
    "solar_permits": {
        "title": "City of Cambridge — solar installation permits",
        "url": "https://data.cambridgema.gov/resource/whpw-w55x.json",
        "description": "Up to five solar permit candidates within 250 m. No returned permit "
        "does not establish absence of solar or batteries.",
        "data_kind": "published_solar_permit_candidates",
        "match_method": "within_250m_candidate",
        "coverage": {
            "region": "Massachusetts",
            "scope": "municipal adapter",
            "municipalities": ["CAMBRIDGE"],
        },
    },
    "assessor_records": {
        "title": "Municipal public assessor cards",
        "url": "https://www.mass.gov/info-details/massachusetts-interactive-property-map",
        "description": "Address/parcel-based municipal records, photos and sketches; "
        "supported municipal adapters report blocked access explicitly.",
        "data_kind": "reported_assessor_card",
        "match_method": "parcel_address_candidate",
        "coverage": {
            "region": "Massachusetts",
            "scope": "municipal adapter",
            "municipalities": ["CAMBRIDGE", "HOLLISTON", "NEWTON", "NORTHAMPTON"],
        },
    },
    "municipal_archives": {
        "title": "Municipal public archive searches",
        "url": "https://portal.laserfiche.com/Portal/Search.aspx?repo=r-65c20b5e",
        "description": "Address-based public search for Holliston, Newton and "
        "Northampton; no login or challenges bypassed.",
        "data_kind": "public_archive_candidates",
        "match_method": "address_search_candidate",
        "coverage": {
            "region": "Massachusetts",
            "scope": "municipal adapter",
            "municipalities": ["HOLLISTON", "NEWTON", "NORTHAMPTON"],
        },
    },
    "land_records": {
        "title": "MassGIS registry district and public recorded-document discovery",
        "url": "https://s3.us-east-1.amazonaws.com/download.massgis.digital.mass.gov/shapefiles/state/regdeeds.zip",
        "description": "Find containing registry district, retain parcel book/page references "
        "and attempt its public record route.",
        "data_kind": "public_registry",
        "match_method": "district_containing_point",
        "coverage": {"region": "Massachusetts", "scope": "statewide public source"},
    },
    "tariffs": {
        "title": "Utility-published tariff candidates",
        "url": "https://www.mass.gov/info-details/massachusetts-electric-rates-and-tariffs",
        "description": "Retrieve official utility schedule PDFs and quoted rate-component "
        "mentions; no account data.",
        "data_kind": "public_tariff_components",
        "match_method": "utility_area_schedule_candidate",
        "coverage": {
            "region": "Massachusetts",
            "scope": "utility candidates from public directory; discovery may be "
            "blocked",
        },
    },
}

DEFAULT_SOURCES = list(SOURCES)
DEPENDENT_SOURCES = {
    "permits",
    "assessor_records",
    "municipal_archives",
    "land_records",
    "tariffs",
}

REFERENCES = {
    "land_records": {
        "status": "manual_lookup",
        "url": "https://www.mass.gov/news/finding-your-property-records",
        "description": "The land_records adapter resolves the registry district and recorded "
        "references, attempts public document discovery and reports blocked "
        "image access explicitly.",
    },
    "permits": {
        "status": "manual_lookup",
        "url": None,
        "description": "Municipal portals vary. Search the returned address/parcel for plans and "
        "later alterations. Cambridge permits and exposed public files can be "
        "retrieved as candidates; archived/as-built plans still require "
        "confirmation.",
    },
    "tariff_documents": {
        "status": "reference_only",
        "url": "https://www.mass.gov/info-details/massachusetts-electric-rates-and-tariffs",
        "description": "Official tariff directory. Published candidate schedules and "
        "effective dates are retrieved by the tariffs adapter; "
        "applicability is not inferred.",
    },
}

MUNICIPAL_PORTALS = {
    "ATTLEBORO": "https://permiteyes.net/Attleboro/building/homepage.asp",
    "HOLLISTON": "https://www.townofholliston.us/187/Building",
    "NEWTON": "https://newtonma.portal.opengov.com/",
    "NORTHAMPTON": "https://northamptonma.portal.opengov.com/",
    "CAMBRIDGE": "https://www.cambridgema.gov/en/iwantto/applyforabuildingpermit",
    "BOSTON": "https://www.boston.gov/departments/inspectional-services",
}


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
                **intake_record(source, feature["attributes"]),
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
    if source not in SOURCES:
        raise ValueError(f"Source {source!r} is outside Option 1. See /sources.")
    context = context or {}
    with requests.Session() as session:
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
        if source == "tariffs":
            return public_energy.tariffs(
                session, municipality, context, cache_dir, refresh
            )
        if source in ("permits", "electrical_permits", "solar_permits"):
            if source == "permits" and municipality == "ATTLEBORO":
                return attleboro_permits(session, context, cache_dir)
            if municipality != "CAMBRIDGE":
                coverage = "Cambridge and Attleboro" if source == "permits" else "Cambridge"
                return {
                    "status": "unsupported",
                    "records": [],
                    "truncated": False,
                    "detail": f"This permit adapter covers {coverage}; no adapter is configured for {municipality or 'the unresolved municipality'}. Statewide sources still query the requested point. No sample-site records are substituted.",
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
            records = [
                intake_record(source, r)
                for r in get_json(session, SOURCES[source]["url"], params)
            ]
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
            datasets = lber_datasets(session)
            for dataset in datasets:
                url = dataset["url"]
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
                                **intake_record("lber", f["attributes"]),
                                "geometry": f.get("geometry", {}),
                                "data_year": f["attributes"].get("Reporting_Year")
                                or f["attributes"].get("Data_Year"),
                                "dataset_name": dataset["name"],
                                "_source_url": query_url,
                            }
                            normalized = {
                                re.sub(r"[^a-z0-9]", "", key.lower()): value
                                for key, value in r.items()
                            }
                            value = normalized.get(
                                "totalelectricityusepurchasedfromgridkbtu"
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
                            generation = normalized.get(
                                "totalelectricitygeneratedfromonsiterenewableskbtu"
                            )
                            try:
                                r["annual_onsite_generation_kwh"] = (
                                    float(generation) / KBTU_PER_KWH
                                    if generation is not None
                                    else None
                                )
                            except (TypeError, ValueError):
                                r["annual_onsite_generation_kwh"] = None
                            records.append(r)
                        if not payload.get("exceededTransferLimit"):
                            break
                        if offset == 900:
                            truncated = True
                except Exception as error:
                    errors.append({"dataset": dataset["name"], "error": str(error)})
            return {
                "records": records,
                "queries": queries,
                "document_errors": errors,
                "truncated": truncated,
                "years": sorted(
                    {r["data_year"] for r in records if r.get("data_year") is not None}
                ),
                "datasets": datasets,
                "discovery_url": LBER_CATALOG,
            }
        return query_point(session, source, latitude, longitude)
