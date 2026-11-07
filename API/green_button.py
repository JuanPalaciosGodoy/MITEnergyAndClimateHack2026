"""Green Button Download My Data XML to Polars interval energy.

Supports incremental Wh readings. Other units or cumulative registers fail
explicitly so their values cannot silently become incorrect load profiles.
See https://www.greenbuttonalliance.org/poweroftenmultiplier.
"""

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import polars as pl

GREEN_BUTTON_SAMPLE = (
    "https://s3-us-west-2.amazonaws.com/technical.greenbuttonalliance.org/"
    "library/sample-data/TestGBDataHourlyNineDaysBinnedDaily.xml"
)
NS = {"a": "http://www.w3.org/2005/Atom", "e": "http://naesb.org/espi"}


def read_green_button(path, *, source_url=None, data_kind="customer_provided"):
    """Return separate meter streams in UTC, preserving units and quality codes.

    Input must be a complete Atom feed containing MeterReading, ReadingType,
    and IntervalBlock entries with their self/related links. No account login
    or Connect My Data OAuth flow is performed here.
    """
    path = Path(path)
    source_url = source_url or path.resolve().as_uri()
    content = path.read_bytes()
    root = ET.fromstring(content)
    entries = {}
    for entry in root.findall("a:entry", NS):
        link = entry.find("a:link[@rel='self']", NS)
        if link is not None:
            entries[urljoin(source_url, link.attrib["href"]).rstrip("/")] = entry

    rows = []
    for uri, entry in entries.items():
        block = entry.find("a:content/e:IntervalBlock", NS)
        if block is None:
            continue
        meter_uri = uri.rsplit("/IntervalBlock/", 1)[0]
        if meter_uri not in entries:
            raise ValueError(f"Missing MeterReading entry for {meter_uri}")
        type_links = [
            urljoin(source_url, link.attrib["href"]).rstrip("/")
            for link in entries[meter_uri].findall("a:link[@rel='related']", NS)
            if "/ReadingType/" in link.attrib["href"]
        ]
        if len(type_links) != 1 or type_links[0] not in entries:
            raise ValueError(f"Missing or ambiguous ReadingType for {meter_uri}")
        reading_type = entries[type_links[0]].find("a:content/e:ReadingType", NS)
        uom = reading_type.findtext("e:uom", namespaces=NS)
        accumulation = reading_type.findtext("e:accumulationBehaviour", namespaces=NS)
        if uom != "72" or accumulation != "4":
            raise ValueError(
                f"Unsupported ReadingType {type_links[0]}: uom={uom}, "
                f"accumulationBehaviour={accumulation}. Expected incremental Wh (72, 4)."
            )
        multiplier = int(reading_type.findtext("e:powerOfTenMultiplier", default="0", namespaces=NS))
        for reading in block.findall("e:IntervalReading", NS):
            duration = int(reading.findtext("e:timePeriod/e:duration", namespaces=NS))
            if duration <= 0:
                raise ValueError(f"Nonpositive interval duration in {uri}")
            rows.append({
                "meter_reading_uri": meter_uri,
                "reading_type_uri": type_links[0],
                "source_locator": uri,
                "start_epoch_seconds": int(reading.findtext("e:timePeriod/e:start", namespaces=NS)),
                "duration_seconds": duration,
                "value_raw": int(reading.findtext("e:value", namespaces=NS)),
                "uom": uom,
                "power_of_ten_multiplier": multiplier,
                "flow_direction": reading_type.findtext("e:flowDirection", namespaces=NS),
                "phase": reading_type.findtext("e:phase", namespaces=NS),
                "commodity": reading_type.findtext("e:commodity", namespaces=NS),
                "reading_quality": ",".join(q.text or "" for q in reading.findall("e:ReadingQuality/e:quality", NS)),
            })
    if not rows:
        raise ValueError("No IntervalReading records found in this Green Button Atom feed.")
    return (
        pl.from_dicts(rows, infer_schema_length=None)
        .with_columns(
            interval_start_utc=pl.from_epoch("start_epoch_seconds", time_unit="s").dt.replace_time_zone("UTC"),
            energy_kwh=pl.col("value_raw") * pl.lit(10.0).pow(pl.col("power_of_ten_multiplier")) / 1000,
            source_url=pl.lit(source_url),
            source_sha256=pl.lit(hashlib.sha256(content).hexdigest()),
            retrieved_at_utc=pl.lit(datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)),
            data_kind=pl.lit(data_kind),
            geography=pl.lit("unspecified"),
        )
        .with_columns(
            interval_end_utc=pl.col("interval_start_utc") + pl.duration(seconds=pl.col("duration_seconds")),
            average_kw=pl.col("energy_kwh") * 3600 / pl.col("duration_seconds"),
        )
        .sort("meter_reading_uri", "interval_start_utc")
    )
