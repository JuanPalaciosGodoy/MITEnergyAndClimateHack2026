"""Audited units for Option 1 values; never infer physical units from magnitude."""

import re

NOT_APPLICABLE = "not_applicable"
UNKNOWN = "unknown"
COORDINATE_UNIT = "degrees (WGS84)"

# Canonical names and flattened provider aliases. Annual totals are energy,
# not power; their reporting period is carried separately in the source record.
_FIELD_UNITS = {
    "assessor_building_area_sqft": "ft²",
    "BLD_AREA": "ft²",
    "roofprint_area_sqft": "ft²",
    "AREA_SQ_FT": "ft²",
    "floor_area_sqft": "ft²",
    "Gross_Floor_Area": "ft²",
    "Land Area (sq. ft)": "ft²",
    "Living Area (sq. ft.)": "ft²",
    "annual_electricity_kwh": "kWh",
    "annual_onsite_generation_kwh": "kWh",
    "Total_Electricity_Use_Purchased_From_Grid_kBtu": "kBtu",
    "Total_Electricity_Generated_from_Onsite_Renewables_kBtu": "kBtu",
    "Onsite_Generation_kBtu": "kBtu",
    "service_voltage_v": "V",
    "volts_existing_service": "V",
    "volts_new_service": "V",
    "reported_existing_service_volts": "V",
    "reported_new_service_volts": "V",
    "service_phases": "phases",
    "service_amperage_a": "A",
    "amps_existing_service": "A",
    "amps_new_service": "A",
    "reported_existing_service_amps": "A",
    "reported_new_service_amps": "A",
    "ampacity": "A",
    "transformer_rating_kva": "kVA",
    "kva": "kVA",
    "reported_kva_raw": "kVA",
    "reported_ups_total_kva": "kVA",
    # Cambridge solar dataset metadata explicitly specifies kW DC and W per panel.
    "solar_system_size": "kW DC",
    "reported_system_size_raw": "kW DC",
    "watt_capacity": "W/panel",
    "reported_watt_capacity_raw": "W/panel",
    "photovoltaic_panels": "count",
    "reported_pv_panel_count": "count",
    "generators": "count",
    "reported_generator_count": "count",
    "photovoltaic_panel_count": "count",
    "reported_panel_count": "count",
    "inverter_count": "count",
    "count_of_meters_existing": "count",
    "count_of_meters_new_service": "count",
    "existing_meter_count": "count",
    "new_meter_count": "count",
    "record_count": "count",
    "Number of Units": "count",
    "page": "page",
    "number_of_stories": "stories",
    "STORIES": "stories",
    "Number of Stories": "stories",
    "year_built": "year",
    "data_year": "year",
    "Reporting_Year": "year",
    "Data_Year": "year",
    "Year of Assessment": "year",
    "FY": "year",
    "latitude": COORDINATE_UNIT,
    "longitude": COORDINATE_UNIT,
    "source_distance_m": "m",
}


def _key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("²", "2").replace("³", "3"))


UNITS = {_key(name): unit for name, unit in _FIELD_UNITS.items()}
_IDENTIFIERS = {
    _key(name)
    for name in "id permit_id entry_id OBJECTID FID UBID parcel_id municipal_parcel_id municipal_property_id massgis_parcel_id MAP_PAR_ID LOC_ID PROP_ID PLAN_ID REG_ID TOWN_ID mbl LS_BOOK LS_PAGE Number AddressNum ZIP ZIP_Code USE_CODE StateClassCode Map/Lot Book/Page Legal1".split()
}
_NON_MEASUREMENTS = {
    _key(name)
    for name in "source_date source_title source_date_basis issue_date applicant_submit_date permit_type building_use description document_excerpt component_text interpretation document_role url source_url local_file specific_url detail_url source_date_basis dataset_name parcel_land_area_unit LOT_UNITS unit_raw rate_assignment schedule eligibility status reported_status existing_service overhead_existing underground_existing overhead_new_service underground_new_service parcel_match parcel_relation relation_status location_limit match_method search_method text_status record_kind search_address address full_address municipality state city recorded_owner Property_Class State_Class_Code Zoning Owner1 Owner(s) Land_Use Property_Type Property_Name Parent_Child_Status Reporting_Boundary section extension name entry_properties Style Occupancy Exterior_Wall_Type Roof_Material Overall_Condition Unit_Type inverter_type solar_energy_type mount_type public_reference_links registry_website WEBSITE DISTRICT source_location_basis search_address deed_retrieved recorded_plan_retrieved document_access access_detail existing_site_solar existing_generators existing_batteries transfer_switches single_line_diagram point_of_interconnection battery_storage_capacity reported_battery_field_raw reported_battery_installation_flag".split()
}
_AREA_UNITS = {
    "ac": "acre",
    "acre": "acre",
    "acres": "acre",
    "sf": "ft²",
    "sqft": "ft²",
    "squarefeet": "ft²",
    "squarefoot": "ft²",
    "ft2": "ft²",
    "sqm": "m²",
    "squaremeters": "m²",
    "squaremetres": "m²",
    "m2": "m²",
}
_TOKEN_UNITS = {
    "kva": "kVA",
    "kvar": "kVAr",
    "kwh": "kWh",
    "kw": "kW",
    "w": "W",
    "v": "V",
    "vac": "V AC",
    "vdc": "V DC",
    "volt": "V",
    "volts": "V",
    "a": "A",
    "amp": "A",
    "amps": "A",
    "kbtu": "kBtu",
    "btu": "Btu",
    "ft²": "ft²",
    "ft2": "ft²",
    "sqft": "ft²",
    "m²": "m²",
    "m2": "m²",
    "acre": "acre",
    "acres": "acre",
    "ac": "acre",
    "ft": "ft",
    "feet": "ft",
    "foot": "ft",
    "m": "m",
    "meters": "m",
    "metres": "m",
}
_SI_PREFIX_UNITS = {
    unit: unit for unit in ("mV", "kV", "mA", "kA", "MW", "mW", "MWh", "mWh")
}


def _stated_units(value):
    if not isinstance(value, str):
        return set()
    tokens = re.findall(
        r"\d[\d,.]*\s*(kVAr|kVA|kWh|kW|kBtu|Btu|MWh|mWh|MW|mW|mV|kV|mA|kA|VAC|VDC|volts?|amps?|V|A|W|ft²|ft2|sqft|m²|m2|acres?|ac|feet|foot|ft|meters|metres|m)\b(?:\s+(AC|DC)\b)?",
        value,
        re.I,
    )
    result = set()
    for token, basis in tokens:
        unit = _SI_PREFIX_UNITS.get(token) or _TOKEN_UNITS.get(token.lower(), UNKNOWN)
        if basis and unit in ("kW", "V"):
            unit += " " + basis.upper()
        result.add(unit)
    return result


_NUMBER = re.compile(r"^[+-]?(?:\d[\d,]*(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def value_leaves(name, value):
    """One value per unit, including nested assessor labels and document ratings."""
    if isinstance(value, dict) and name.endswith(".detail_url"):
        yield name, value.get("url")
    elif isinstance(value, dict) and "record_count" in value:
        yield name + ".record_count", value["record_count"]
    elif isinstance(value, dict) and value:
        for key, item in value.items():
            yield from value_leaves(name + "." + key, item)
    elif isinstance(value, list) and value:
        for index, item in enumerate(value, 1):
            yield from value_leaves(f"{name}[{index}]", item)
    else:
        yield name, value


def value_unit(source, name, value, record=None):
    """Unit for the subcategory value, not for the provenance columns beside it."""
    record = record or {}
    path = re.sub(r"\[\d+\]", "", name)
    if path.endswith(".ambiguous_candidates"):
        path = path.removesuffix(".ambiguous_candidates")
    leaf = (
        path.split("reported_assessor_attributes.", 1)[-1]
        if "reported_assessor_attributes." in path
        else path.rsplit(".", 1)[-1]
    )
    key = _key(leaf)
    if isinstance(value, (bool, dict, list)):
        return NOT_APPLICABLE
    # The same spelling in a different municipal schema does not establish units.
    if key == "parcellandarea" or (source == "parcels" and key == "lotsize"):
        expected = _AREA_UNITS.get(_key(str(record.get("LOT_UNITS") or "")), UNKNOWN)
        stated = _stated_units(value)
        return UNKNOWN if stated and stated != {expected} else expected
    if source == "assessor_records" and key in {"lotsize", "frontage", "wallheight"}:
        stated = _stated_units(value)
        allowed = {"ft²", "m²", "acre"} if key == "lotsize" else {"ft", "m"}
        return next(iter(stated)) if len(stated) == 1 and stated <= allowed else UNKNOWN
    if key in UNITS:
        expected = UNITS[key]
        stated = _stated_units(value)
        if not stated or stated == {expected}:
            return expected
        if expected == "V" and len(stated) == 1 and stated <= {"V AC", "V DC"}:
            return next(iter(stated))
        if expected == "kW DC" and stated == {"kW"}:
            return expected
        if expected == "W/panel" and stated == {"W"}:
            return expected
        return UNKNOWN
    if key == "datemodif":
        return (
            "ms since Unix epoch (UTC)"
            if isinstance(value, (int, float))
            else NOT_APPLICABLE
        )
    if source == "tariffs" and key == "amountsraw":
        # Bind a price only to the unit phrase immediately following that price.
        # A unit elsewhere in the same PDF line may belong to another column.
        text = record.get("component_text", "")
        prices = list(re.finditer(r"\$\s*([0-9,]+(?:\.[0-9]+)?)", text))
        indexes = re.findall(r"\[(\d+)\]", name)
        index = int(indexes[-1]) - 1 if indexes else 0
        if index >= len(prices):
            return "USD (billing basis unknown)"
        suffix = text[prices[index].end() :]
        phrase = re.match(
            r"\s*((?:(?:per|/)\s*(?:kWh|kW|month|meter|day)\b\s*)+)", suffix, re.I
        )
        if not phrase:
            return "USD (billing basis unknown)"
        bases = re.findall(r"(?:per|/)\s*(kWh|kW|month|meter|day)\b", phrase[1], re.I)
        labels = {
            "kwh": "kWh",
            "kw": "kW",
            "month": "month",
            "meter": "meter",
            "day": "day",
        }
        return "USD/" + "/".join(labels[base.lower()] for base in bases)
    if (
        key in _IDENTIFIERS
        or key in _NON_MEASUREMENTS
        or key.endswith("error")
        or key.endswith("coverage")
    ):
        return NOT_APPLICABLE
    if key == "ratingsraw":
        units = _stated_units(value)
        return next(iter(units)) if len(units) == 1 else UNKNOWN
    if isinstance(value, (int, float)) or (
        isinstance(value, str) and _NUMBER.fullmatch(value.strip())
    ):
        return UNKNOWN
    return NOT_APPLICABLE
