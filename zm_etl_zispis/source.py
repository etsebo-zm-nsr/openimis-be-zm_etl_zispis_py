from api_etl.sources import BaseHttpSource


class ZispisSource(BaseHttpSource):
    """Pulls individuals/households from the ZISPIS MIS.

    Offset/limit pagination. Everything about the request - URL, method, auth, page
    size, timeouts, retries, TLS/CA bundle, and where the rows live in the response
    envelope - is configuration, so a contract change does not require a code change.
    """

    def pull(self):
        yield from self.iter_offset_pages(extra_params=self._incremental_params())

    def _incremental_params(self):
        """Restrict the pull to records changed since the last successful sync."""
        incremental = self.cfg.incremental
        if not incremental.enabled or not incremental.cursor_param:
            return {}
        watermark = self.effective_watermark()
        if not watermark:
            return {}
        return {incremental.cursor_param: watermark}
