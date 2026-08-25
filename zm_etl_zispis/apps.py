from django.apps import AppConfig

MODULE_NAME = "zm_etl_zispis"

# Rights are per-connector so access can be granted per source rather than
# "may trigger every ETL in the system". Malawi's msr_etl reuses api_etl's 953001/953002
# for exactly this reason and loses that distinction.
ZISPIS_TRIGGER_RIGHT = "953101"

DEFAULT_CONFIG = {
    "enabled": True,
    "auth": {
        "type": "basic",
        "username": "",
        # Never store a real credential here - ModuleConfiguration.config is a plain
        # TextField that lands in every DB backup. "env:NAME" reads from the process env.
        "password": "env:ZISPIS_API_PASSWORD",
    },
    "source": {
        "http_method": "GET",
        "url": "",
        "batch_size": 200,
        "timeout_seconds": 120,
        "retry_total": 3,
        "retry_backoff_factor": 1.0,
        "verify_ssl": True,
        # Government APIs often present a custom or self-signed certificate.
        "ca_bundle_path": "",
        "offset_param": "offset",
        "limit_param": "limit",
        "response": {
            "rows_key": "rows",
            "status_key": None,
            "message_key": "message",
        },
    },
    "adapter": {
        "field_map": {
            "first_name": "firstName",
            "last_name": "lastName",
            "dob": "dateOfBirth",
            "location_name": "locationName",
            "location_code": "locationCode",
        },
        "external_id_field": "id",
        "external_id_prefix": "zispis:",
        "group_code_field": "householdId",
        "group_code_prefix": "zm-hh-zispis:",
        "role_field": "relationship",
        "role_map": {
            "head": "HEAD", "spouse": "SPOUSE", "son": "SON", "daughter": "DAUGHTER",
            "other relative": "OTHER_RELATIVE", "not related": "NOT_RELATED",
        },
        "recipient_field": "isRecipient",
        "national_id_field": "nrc",
        "date_formats": ["%Y-%m-%d", "%d/%m/%Y"],
    },
    "sink": {
        "lookup_field": "json_ext__external_id",
        "update_existing": True,
    },
    "incremental": {
        "enabled": False,
        "mode": "query_param",
        "cursor_field": "lastModified",
        "cursor_param": "updatedSince",
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
