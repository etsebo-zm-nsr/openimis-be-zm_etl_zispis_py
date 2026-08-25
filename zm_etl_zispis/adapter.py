from api_etl.adapters import BaseMappingAdapter


class ZispisAdapter(BaseMappingAdapter):
    """Maps ZISPIS records onto the individual import columns.

    Field mapping, identifier namespacing, household code, role mapping and national-ID
    handling are all driven by `adapter.*` config, so this class carries no logic of its
    own. It exists as a named type so the connector has a stable class to register and
    somewhere obvious to put ZISPIS-specific handling if the API later needs it.
    """
