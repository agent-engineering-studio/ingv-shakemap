"""An async client for the INGV event catalogue and the ShakeMap grids.

Give it your ``httpx.AsyncClient`` and timeouts, proxies and pooling stay
yours; give it none and it opens (and closes) its own. Network errors and
429/5xx are retried ``retries`` times with exponential backoff.

To route every request through your own HTTP layer (a shared retry policy,
a cache, a rate limiter), pass ``send``: an ``async (method, url, **kwargs)
-> httpx.Response``. The client then uses it for every call and does no
retrying of its own.

What the services answer, and what you get back:

* no events in the window: the FDSN service says **204**, you get ``[]``;
* an event with no ShakeMap (small or too recent): **404**, you get ``None``;
* anything else that is not a success raises :class:`IngvError`, so an
  unreachable catalogue never looks like a quiet week.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from types import TracebackType
from typing import Any

import httpx

from ingv_shakemap.errors import IngvError
from ingv_shakemap.events import (
    FDSN_EVENT_URL,
    ITALY,
    SHAKEMAP_BASE,
    BBox,
    Event,
    event_query,
    parse_events,
    shakemap_product_url,
)
from ingv_shakemap.grid import ShakeGrid, parse_grid
from ingv_shakemap.products import ShakeMapInfo, Station, parse_info, parse_stations

Send = Callable[..., Awaitable[httpx.Response]]
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})


class IngvClient:
    """The INGV FDSN event service and the ShakeMap grids."""

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        send: Send | None = None,
        retries: int = 3,
        backoff_s: float = 2.0,
        timeout_s: float = 60.0,
        event_url: str = FDSN_EVENT_URL,
        shakemap_base: str = SHAKEMAP_BASE,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._own = client is None and send is None
        self._client = client or (
            None if send is not None else httpx.AsyncClient(follow_redirects=True)
        )
        self._send_hook = send
        self._retries = retries
        self._backoff_s = backoff_s
        self._timeout_s = timeout_s
        self._event_url = event_url
        self._shakemap_base = shakemap_base
        self._sleep = sleep

    async def __aenter__(self) -> IngvClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the HTTP client if this instance opened it."""
        if self._own and self._client is not None:
            await self._client.aclose()

    async def events(
        self,
        start: datetime,
        end: datetime,
        *,
        bbox: BBox = ITALY,
        min_magnitude: float | None = None,
        max_depth_km: float | None = None,
        limit: int | None = None,
        updated_after: datetime | None = None,
    ) -> list[Event]:
        """The earthquakes in ``bbox`` between ``start`` and ``end``, newest first.

        With ``updated_after``, only those created or revised after it.
        """
        params = event_query(
            start,
            end,
            bbox=bbox,
            min_magnitude=min_magnitude,
            max_depth_km=max_depth_km,
            limit=limit,
            updated_after=updated_after,
        )
        response = await self._send("GET", self._event_url, params=params)
        # The error first: a 5xx with no body is not a window with no earthquakes.
        if response.status_code >= 400:
            raise IngvError(f"FDSN event service: HTTP {response.status_code}")
        if response.status_code == 204 or not response.content:
            return []
        try:
            payload = response.json()
        except ValueError as exc:
            raise IngvError("FDSN event service: not JSON") from exc
        return parse_events(payload)

    async def product(self, event_id: str | int, name: str) -> bytes | None:
        """One file of an event's ShakeMap, raw; ``None`` if INGV published none.

        ``name`` is ``grid.xml``, ``uncertainty.xml``, ``info.json``,
        ``stationlist.json`` or any other file of the map's products.
        """
        url = shakemap_product_url(event_id, name, base=self._shakemap_base)
        response = await self._send("GET", url)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise IngvError(f"ShakeMap {event_id} {name}: HTTP {response.status_code}")
        return bytes(response.content)

    async def shakemap_xml(self, event_id: str | int) -> bytes | None:
        """The raw ``grid.xml`` of an event; ``None`` if INGV published no ShakeMap."""
        return await self.product(event_id, "grid.xml")

    async def shakemap(self, event_id: str | int) -> ShakeGrid | None:
        """The ShakeMap of an event, parsed in a thread; ``None`` if there is none."""
        return await self._grid(event_id, "grid.xml")

    async def uncertainty(self, event_id: str | int) -> ShakeGrid | None:
        """The map's uncertainty (``STDPGA`` in ln g, ``STDPGV``, ``STDMMI``...) as a grid.

        Low near the stations, high where the map is the model alone.
        """
        return await self._grid(event_id, "uncertainty.xml")

    async def info(self, event_id: str | int) -> ShakeMapInfo | None:
        """The map's ``info.json``: its version and status for a few kB, not 12 MB."""
        payload = await self._json(event_id, "info.json")
        return None if payload is None else parse_info(payload)

    async def stations(self, event_id: str | int) -> list[Station] | None:
        """The stations behind the map, with what they recorded."""
        payload = await self._json(event_id, "stationlist.json")
        return None if payload is None else parse_stations(payload)

    async def _grid(self, event_id: str | int, name: str) -> ShakeGrid | None:
        xml = await self.product(event_id, name)
        if xml is None:
            return None
        return await asyncio.to_thread(parse_grid, xml)

    async def _json(self, event_id: str | int, name: str) -> dict[str, Any] | None:
        content = await self.product(event_id, name)
        if content is None:
            return None
        try:
            payload = json.loads(content)
        except ValueError as exc:
            raise IngvError(f"ShakeMap {event_id} {name}: not JSON") from exc
        if not isinstance(payload, dict):
            raise IngvError(f"ShakeMap {event_id} {name}: not a JSON object")
        return payload

    async def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        if self._send_hook is not None:
            return await self._send_hook(method, url, **kwargs)
        assert self._client is not None
        kwargs.setdefault("timeout", self._timeout_s)
        for attempt in range(self._retries + 1):
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if attempt == self._retries:
                    raise IngvError(f"{url}: {exc}") from exc
            else:
                if response.status_code not in _RETRY_STATUS or attempt == self._retries:
                    return response
            await self._sleep(self._backoff_s * 2**attempt)
        raise AssertionError("unreachable")  # pragma: no cover


__all__ = ["IngvClient", "Send"]
