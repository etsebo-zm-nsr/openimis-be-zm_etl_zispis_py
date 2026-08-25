# Zambia Social Registry — ZISPIS ETL connector

`openimis-be-zm_etl_zispis` pulls individual and household records from the ZISPIS MIS
into openIMIS.

It is a **connector**: it owns only what is ZISPIS-specific — how that API paginates,
how its fields map, and its own credentials. The sink, record linkage, sync state,
scheduling, auth and HTTP plumbing all come from the shared `api_etl` core, so behaviour
that must not diverge between sources (national-ID normalisation, household grouping,
identity matching) has exactly one implementation.

## Layout

| File | Purpose |
|---|---|
| `apps.py` | `DEFAULT_CONFIG` + registration into the `api_etl` registry |
| `source.py` | offset pagination + incremental watermark parameter |
| `adapter.py` | named type; the mapping itself is configuration |
| `service.py` | binds source + adapter; everything else inherited |

## Install

```json
{ "name": "zm_etl_zispis", "pip": "-e /path/to/openimis-be-zm_etl_zispis_py" }
```

Must be listed **after** `api_etl` in `openimis.json`.

## Configure

Edit the `zm_etl_zispis` `ModuleConfiguration` row. Never put a real credential in it —
that table lands in every database backup. Use `"env:VAR_NAME"` and set the variable in
the deployment environment:

```json
{ "auth": { "username": "zm-registry", "password": "env:ZISPIS_API_PASSWORD" },
  "source": { "url": "https://zispis.example/api/beneficiaries" } }
```

Config is deep-merged over the defaults, so a partial override keeps its siblings.

## Rights

`953101` — trigger the ZISPIS sync. Granted to *IMIS Administrator* by migration `0001`.
