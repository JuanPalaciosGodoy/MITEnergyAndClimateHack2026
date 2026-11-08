"""Option 1 intake fields. Original public documents remain evidence, not schema."""

import re

SCOPE = "option_1_site_intake"

# Keep identifiers/locations/dates needed to match and trace published facts.
PROVENANCE = set(
    "geometry centroid coordinates _location _source_url source_url source_title source_date source_date_basis match_method local_file retrieved_at_utc".split()
)
RECORD_FIELDS = {
    "utilities": "TOWN TOWN_ID ELEC",
    "parcels": "OBJECTID LOC_ID MAP_PAR_ID PROP_ID PLAN_ID REG_ID TOWN_ID SITE_ADDR CITY ZIP OWNER1 USE_CODE USE_DESC ZONING BLD_AREA LOT_SIZE LOT_UNITS YEAR_BUILT STORIES STYLE UNITS LS_BOOK LS_PAGE FY LAST_EDIT",
    "buildings": "OBJECTID STRUCT_ID AREA_SQ_FT SOURCEDATE",
    "lber": "FID UBID Latitude Longitude latitude longitude Street_Address City ZIP_Code Property_Type Property_Name Gross_Floor_Area Parent_Child_Status Reporting_Boundary Reporting_Year Data_Year Year_Built Total_Electricity_Use_Purchased_From_Grid_kBtu Total_Electricity_Generated_from_Onsite_Renewables_kBtu Onsite_Generation_kBtu building_id address city floor_area_sqft data_year dataset_name annual_electricity_kwh annual_onsite_generation_kwh",
    "permits": "id full_address latitude longitude permit_type permit_number issue_date applicant_submit_date status description proposed_work_description specific_url search_address mbl",
    "electrical_permits": "id full_address latitude longitude issue_date applicant_submit_date status permit_type building_permit building_use mbl existing_service volts_existing_service amps_existing_service volts_new_service amps_new_service ampacity kva count_of_meters_existing count_of_meters_new_service overhead_existing underground_existing overhead_new_service underground_new_service generators photovoltaic_panels proposed_work_description description specific_url",
    "solar_permits": "id full_address latitude longitude issue_date applicant_submit_date status permit_type mbl work_description solar_energy_type solar_system_size watt_capacity photovoltaic_panel_count inverter_count inverter_type inverter_make_and_model mount_type battery_storage_capacity specific_url",
    "assessor_records": "address municipal_parcel_id massgis_parcel_id municipal_property_id parcel_match document_role search_method search_address section reported_assessor_attributes text_status record_kind MAP_PAR_ID Number AddressNum Street Owner1 Land_Use Zoning Lot_Size Frontage Year_Built Legal1 Date_Modif LOC_ID",
    "municipal_archives": "entry_id name extension entry_properties search_address location_limit record_kind address municipal_property_id",
    "land_records": "DISTRICT WEBSITE registry_website record_kind parcel_deed_references deed_retrieved recorded_plan_retrieved document_access access_detail public_reference_links",
    "tariffs": "component_text amounts_raw unit_raw cross_reference rate_assignment url page document_role schedule eligibility",
}
_ALLOWED = {
    source: {re.sub(r"[^a-z0-9]", "", field.lower()) for field in fields.split()}
    for source, fields in RECORD_FIELDS.items()
}
_ASSESSOR_LABELS = {
    "Property Class",
    "State Class Code",
    "Zoning (Unofficial)",
    "Map/Lot",
    "Land Area (sq. ft)",
    "Year of Assessment",
    "Book/Page",
    "Owner(s)",
    "Style",
    "Occupancy",
    "Number of Stories",
    "Exterior Wall Type",
    "Roof Material",
    "Wall Height",
    "Living Area (sq. ft.)",
    "Number of Units",
    "Year Built",
    "Overall Condition",
    "Description",
    "Unit Type",
}


def intake_record(source, record):
    """A positive field list prevents later-phase/provider form fields leaking out."""
    allowed = _ALLOWED[source]
    result = {
        key: value
        for key, value in record.items()
        if key in PROVENANCE or re.sub(r"[^a-z0-9]", "", key.lower()) in allowed
    }
    if isinstance(result.get("reported_assessor_attributes"), dict):
        result["reported_assessor_attributes"] = {
            key: value
            for key, value in result["reported_assessor_attributes"].items()
            if key in _ASSESSOR_LABELS
        }
    return result
