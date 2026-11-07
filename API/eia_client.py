"""Browse EIA API v2 datasets and stream their data rows."""

import logging
import os
from collections.abc import Iterator, Sequence

import requests

from ._http import APIError, get_json

logger = logging.getLogger(__name__)


class EIAClient:
    BASE_URL = "https://api.eia.gov/v2"

    def __init__(self, session: requests.Session | None = None):
        self.session = session if session is not None else requests.Session()
        self.api_key = os.getenv("EIA_API_KEY")
        if not self.api_key:
            raise ValueError("Set EIA_API_KEY before creating EIAClient. Register at https://www.eia.gov/opendata/register.php.")

    def _get(self, route: str, **params) -> dict:
        url = f"{self.BASE_URL}/{route.strip('/')}".rstrip("/") + "/"
        return get_json(self.session, url, {"api_key": self.api_key, **params})["response"]

    def get_metadata(self, route: str = "") -> dict:
        """List child routes or inspect a dataset's fields, frequencies and facets."""
        return self._get(route)

    def get_facet(self, route: str, facet: str, *, length: int = 5000, offset: int = 0) -> dict:
        """Get a page of allowed facet IDs and the provider's totalFacets count."""
        return self._get(f"{route.strip('/')}/facet/{facet}", length=length, offset=offset)

    def iter_data(
        self,
        route: str,
        *,
        frequency: str,
        start: str,
        end: str,
        data: Sequence[str] = ("value",),
        facets: dict[str, str | Sequence[str]] | None = None,
        sort: Sequence[str] = ("period",),
        page_size: int = 5000,
    ) -> Iterator[dict]:
        """Yield raw rows in ascending order, one HTTP page in memory at a time.

        Use EIA period strings, such as 2025-07-15T00 for hourly data. For
        multiple series, add the identifying facet columns to sort to break ties.
        """
        params = {"frequency": frequency, "start": start, "end": end, "data[]": data}
        params.update({f"facets[{name}][]": values for name, values in (facets or {}).items()})
        for index, column in enumerate(sort):
            params[f"sort[{index}][column]"] = column
            params[f"sort[{index}][direction]"] = "asc"

        offset = 0
        while True:
            page = self._get(f"{route.strip('/')}/data", length=page_size, offset=offset, **params)
            rows, total = page["data"], int(page["total"])
            logger.debug("EIA %s offset=%d rows=%d total=%d", route, offset, len(rows), total)
            yield from rows
            offset += len(rows)
            if offset >= total:
                return
            if not rows:
                raise APIError(f"EIA {route} returned an empty page at offset {offset} of {total}.")
