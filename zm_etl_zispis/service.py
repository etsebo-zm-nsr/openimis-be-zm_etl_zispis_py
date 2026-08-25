from api_etl.services import ConnectorETLService

from zm_etl_zispis.adapter import ZispisAdapter
from zm_etl_zispis.source import ZispisSource


class ZispisETLService(ConnectorETLService):
    """ZISPIS -> openIMIS individuals/households.

    The sink, linkage, provenance, sync-state and scheduling all come from the core.
    """
    source_cls = ZispisSource
    adapter_cls = ZispisAdapter
