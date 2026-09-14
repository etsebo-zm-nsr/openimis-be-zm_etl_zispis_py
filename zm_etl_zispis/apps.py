"""ZISPIS connector configuration.

Mapped against the live ZISPIS Beneficiary API v2 (`POST /api/v2/beneficiaries/search`),
verified record-by-record: every path below resolves on real data.

SCOPE. Only fields present in the NSR/ZISPIS mapping workbook are imported - the
harmonized questionnaire plus the ZISPIS-specific questions. The API also returns
payments, status history, photographs, next-of-kin, derived `assessment.calc.*`
counters and programme flags; those are deliberately NOT mapped. Identity and household
structure (beneficiaryId, householdId, householdRole, gender, dateOfBirth, nationalId)
are mapped regardless, because without them there is no person to register.

Everything here is runtime configuration: it ships as DEFAULT_CONFIG and is overridden
per deployment through the Django admin, never through a migration.
"""
from django.apps import AppConfig

MODULE_NAME = "zm_etl_zispis"

# Rights are per-connector so access can be granted per source rather than
# "may trigger every ETL in the system".
ZISPIS_TRIGGER_RIGHT = "953101"

# target registry column -> ZISPIS API path ("a/b/c" resolves nested objects)
ZISPIS_FIELD_MAP = {
    # -- base fields (required by individual_base_fields) --
    "first_name": "firstName",
    "last_name": "lastName",
    "dob": "dateOfBirth",
    # ZISPIS has five administrative levels to openIMIS's four; CWAC is out of scope,
    # so the tiers line up exactly:
    #
    #     province -> R      district -> D      constituency -> W      ward -> V
    #
    # `location_name` is mapped for completeness but BOTH it and `location_code` are
    # overwritten by the core's location resolver, which looks the ward up in the tree
    # loaded from the official GEO file (see adapter.location_match_fields below).
    # openIMIS matches on name AND code together, so both must come from that tree
    # rather than one from ZISPIS and one derived from it.
    "location_name": "location/ward",

    # -- harmonized - present on BOTH the NSR and ZISPIS sides of the workbook --
    "sex": "gender",
    # ZISPIS uses yearOfBirth to derive age; `age` itself is a frozen snapshot from
    # registration. Imported because it is the fallback when dateOfBirth is unusable
    # (see ZispisAdapter.resolve_dob) and a component of the identity key.
    "year_of_birth": "yearOfBirth",
    # ACTIVE / SUSPENDED / GRADUATED. A suspended head is still a member of the
    # household but the household is no longer paid, so this is not cosmetic.
    "status": "status",
    "phone": "phoneNumber",
    "province": "location/province",
    "district": "location/district",
    "constituency": "location/constituency",
    "ward": "location/ward",
    "roof_material": "assessment/dwelling/roofMaterial",
    "wall_material": "assessment/dwelling/wallMaterial",
    "floor_material": "assessment/dwelling/floorMaterial",
    "cooking_energy": "assessment/energy/cookingEnergy",
    "lighting_energy": "assessment/energy/lightingEnergy",
    "agriland_cultivated": "assessment/land/agriLandCultivated",
    "educated_level": "assessment/education/educatedLevel",
    "school_attendance": "assessment/education/schoolAttendance",
    "bursary": "assessment/education/bursary",
    "disability": "vulnerability/hasDisability",

    # -- ZISPIS-specific - geography and dwelling --
    "acc": "location/acc",
    # Kept as an attribute, NOT as a tier: CWAC is out of scope for the location tree
    # (2026-09-09) but the value is still information the registry should hold.
    "cwac": "location/cwac",
    "street_name": "location/address/street",
    "house_number": "location/address/houseNumber",

    # -- ZISPIS-specific - vulnerability --
    "orphanhood": "vulnerability/orphanhood",
    "disability_degree": "vulnerability/disability/degree",
    "disability_cert_type": "vulnerability/disability/certificateType",
    "critical_illness": "vulnerability/chronicIllness/present",
    "critical_illness_cert": "vulnerability/chronicIllness/criticalCert",
    "critical_illness_cert_number": "vulnerability/chronicIllness/criticalCertNum",
    "fit_for_work": "vulnerability/ableBodied",

    # -- ZISPIS-specific - education --
    "school_level": "assessment/education/schoolLevel",
    "school_type": "assessment/education/schoolType",
    "school_name": "assessment/education/schoolName",
    "girls_in_school": "assessment/education/girlsInSchool",
    "qualifies_secondary_school": "assessment/education/qualifySecondarySchool",
    "bursary_status": "assessment/education/bursaryStatus",

    # -- ZISPIS-specific - food security --
    "meals_per_day": "assessment/foodSecurity/mealsPerDay",
    "food_insecurity": "assessment/foodSecurity/foodInsecurity",
    "slept_hungry": "assessment/foodSecurity/sleptHungry",
    "no_food_day_and_night": "assessment/foodSecurity/noFoodDayAndNight",

    # -- ZISPIS-specific - land and livestock --
    "agriland_owned": "assessment/land/agriLandOwned",
    "owns_livestock": "assessment/livestock/ownsLivestock",
    "n_poultry": "assessment/livestock/poultrySize",

    # -- ZISPIS-specific - durable assets (PMT inputs) --
    "asset_clock": "assessment/assets/hasClock",
    "asset_computer": "assessment/assets/hasComputer",
    "asset_radio": "assessment/assets/hasRadio",
    "asset_electric_iron": "assessment/assets/hasElectricIron",
    "asset_television": "assessment/assets/hasTelevision",
    "asset_bicycle": "assessment/assets/hasBicycle",
    "asset_bed": "assessment/assets/hasBed",
    "asset_mattress": "assessment/assets/hasMattress",
    "asset_sofa_lounge_suit": "assessment/assets/hasSofaLoungeSuit",
    "asset_chair": "assessment/assets/hasChair",
    "asset_table": "assessment/assets/hasTable",
    "asset_ox_cart": "assessment/assets/hasOxCart",
    "asset_plough": "assessment/assets/hasPlough",
    "asset_oxdrawn_harrow": "assessment/assets/oxdrawnHarrow",
    "asset_hammer_mill": "assessment/assets/hammerMill",
    "asset_treadle": "assessment/assets/treadle",
    "asset_axe": "assessment/assets/hasAxe",
    "asset_fishnet": "assessment/assets/hasFishNet",
    "asset_hoe": "assessment/assets/hasHoe",
}

DEFAULT_CONFIG = {
    "enabled": True,
    "auth": {
        "type": "basic",
        "username": "",
        # Never a real credential here - ModuleConfiguration.config lands in every DB
        # backup. "env:NAME" reads from the process environment instead.
        "password": "env:ZISPIS_API_PASSWORD",
    },
    "source": {
        # Filters are a JSON document, not a query string.
        "http_method": "POST",
        "request_style": "json_body",
        "url": "",
        # Sent on every request. `createdAt` sorting is NOT cosmetic: paging by
        # lastName returns the same record on multiple pages (18.8% duplicates measured
        # over 2,000 records) because it has heavy ties and no deterministic tie-break,
        # which means a similar share is never returned at all. createdAt is
        # high-cardinality and measured 0% duplicates.
        "body": {
            "sort": ["createdAt:desc"],
            "includeAssessment": True,
            "includeTotal": True,
        },
        "page_param": "page",
        "page_size_param": "pageSize",
        "first_page": 1,                 # page:0 -> 400 INVALID_PAGE
        "batch_size": 200,               # hard API maximum; 201+ -> 400 INVALID_PAGE_SIZE
        "timeout_seconds": 120,
        "retry_total": 3,
        "retry_backoff_factor": 1.0,
        "verify_ssl": True,
        "ca_bundle_path": "",
        "response": {
            "rows_key": "data",
            "has_more_key": "pagination/hasMore",
            "status_key": None,
            "message_key": "message",
        },
    },
    "adapter": {
        "field_map": ZISPIS_FIELD_MAP,
        "external_id_field": "beneficiaryId",
        "external_id_prefix": "zispis:",
        # ZISPIS's household key is the main next-of-kin's NRC (it equals
        # nextOfKinMain.nationalId for ~98% of records), so it changes if that NRC is
        # corrected upstream - see the data-quality doc.
        "group_code_field": "householdId",
        "group_code_prefix": "zm-hh-zispis:",
        "role_field": "householdRole",
        # Gender-dependent roles are resolved in ZispisAdapter.map_role; this covers the
        # values that need no gender to disambiguate.
        "role_map": {
            "HEAD": "HEAD",
            "HUSBAND_OR_WIFE": "SPOUSE",
            "NON_RELATIVE": "NOT_RELATED",
            "DAUGHTER": "DAUGHTER",
            "NEPHEW_OR_NIECE": "OTHER_RELATIVE",
            "COUSIN": "OTHER_RELATIVE",
            "STEPCHILD": "OTHER_RELATIVE",
            "BROTHER_IN_LAW_OR_SISTER_IN_LAW": "OTHER_RELATIVE",
            "SON_IN_LAW_OR_DAUGHTER_IN_LAW": "OTHER_RELATIVE",
            "OTHER_RELATIVE": "OTHER_RELATIVE",
        },
        # ZISPIS names one recipient per household via householdRole == HEAD.
        "recipient_field": "householdRole",
        "national_id_field": "nationalId",
        "national_id_type_field": "nationalIdType",
        "date_formats": ["%Y-%m-%d"],    # plus the ISO fallback in the core
        # ~2% of dateOfBirth values are impossible (years 0002, 0005, 1091). Those
        # resolve to None rather than being asserted as fact.
        "min_year": 1900,
        # ZispisAdapter attaches this in code, to flagged rows only. Declared so
        # `etl_check_schema` counts it - see the adapter's clean_national_id().
        "extra_columns": ["data_quality_note", "dob_source"],
        # WHAT COUNTS AS THE SAME PERSON - defined here and nowhere else.
        # Measured over 5,000 live records (collision = two different source records
        # sharing the key):
        #     national_id alone ............ 34% coverage, 0.94% collisions
        #     first+last+yob+sex ........... 99.9% coverage, 0.24%
        #     first+last+yob+sex+district .. 99.9% coverage, 0.04%   <- chosen
        # national_id is deliberately absent: Zambia issues duplicate NRCs to different
        # people, so it identifies nobody on its own.
        "identity_key_fields": ["first_name", "last_name", "year_of_birth", "sex",
                                "district"],
        # Load everything. ZISPIS's own filters cannot be trusted - unknown filter keys
        # return 200 and are silently ignored - so any filtering happens here, and is
        # left open so a deployment can narrow it from the admin without a code change.
        # e.g. {"status": ["ACTIVE"]} to import only active beneficiaries.
        "include_when": {},
        # Resolve the ward against the loaded gazetteer. ZISPIS sends names only.
        # `province` is deliberately absent: a district name implies its province, and
        # ZISPIS still carries the pre-boundary-change province for CHIRUNDU,
        # ITEZHI-TEZHI and CHAMA - 92 records in a 5,000 sample. Matching from district
        # down ignores that disagreement instead of failing on it.
        "location_match_fields": ["district", "constituency", "ward"],
        # Spellings ZISPIS uses that the gazetteer does not, e.g.
        #     {"district": {"CHIENGI": "CHIENGE"}, "ward": {"NYALA": "NYAALA"}}
        # Left empty deliberately: each entry asserts that two names are the same place,
        # which is the data owner's call, not ours. Populate once confirmed.
        "location_aliases": {},
    },
    "sink": {
        "lookup_field": "json_ext__external_id",
        "update_existing": True,
    },
    "incremental": {
        # MUST stay disabled. The search body accepts no timestamp filter, and unknown
        # keys are accepted with 200 and SILENTLY IGNORED - a watermark of year 2099
        # still returns all 100,000 records. Enabling this would look like incremental
        # sync while full-pulling nightly.
        "enabled": False,
        "mode": "none",
        "cursor_field": None,
        "cursor_param": None,
        "overlap_minutes": 15,
    },
    "provenance": {
        "data_source_label": "ZISPIS",
        "source_type": "api etl:zispis",
        "batch_prefix": "zispis_",
    },
    "schedule": {
        "enabled": False,
        "cron": {"hour": 1, "minute": 0},
    },
    "gql_mutation_trigger_perms": [ZISPIS_TRIGGER_RIGHT],
}


class ZmEtlZispisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = MODULE_NAME

    def ready(self):
        from api_etl.config import config_from_module
        from api_etl.registry import register_etl_source
        from zm_etl_zispis.service import ZispisETLService

        register_etl_source(
            name="zispis",
            service_cls=ZispisETLService,
            # Lazy: resolved per run, so config edits in ModuleConfiguration take effect
            # without a restart and app-loading order does not matter.
            config_provider=lambda: config_from_module(MODULE_NAME, DEFAULT_CONFIG),
            label="ZISPIS (external MIS)",
            trigger_perms=[ZISPIS_TRIGGER_RIGHT],
        )
