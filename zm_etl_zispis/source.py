from api_etl.sources import BaseHttpSource


class ZispisSource(BaseHttpSource):
    """Pulls beneficiaries from the ZISPIS Beneficiary API v2.

    `POST /api/v2/beneficiaries/search` takes its filters and paging as a JSON body and
    pages by page NUMBER (`page`/`pageSize`, 1-based, max 200), reporting
    `pagination.hasMore`. All of that is configuration - request style, parameter names,
    first page index, has-more path - so this class only says which of the core's
    paginators applies.

    The API returns one record per PERSON, already carrying its household context
    (`householdId`, `householdRole`, `householdSize`), so no flattening is needed.

    No incremental pull: the search body accepts no timestamp filter, and unknown keys
    are accepted with 200 and silently ignored, so a watermark parameter would appear to
    work while pulling everything every run. Full pulls are safe because `external_id`
    upserts are idempotent.
    """

    def pull(self):
        yield from self.iter_page_number_pages()
