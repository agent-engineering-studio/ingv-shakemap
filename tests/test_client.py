from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import make_grid_xml

from ingv_shakemap import IngvClient, IngvError

_START = datetime(2026, 10, 23, tzinfo=UTC)
_END = _START + timedelta(days=1)
_COLLECTION = {
    "type": "FeatureCollection",
    "features": [
        {
            "properties": {"eventId": 47606532, "time": "2026-10-23T10:19:15", "mag": 5.5},
            "geometry": {"coordinates": [14.1717, 38.7938, 8.8]},
        }
    ],
}


async def _no_sleep(_: float) -> None:
    return None


def _client(handler: Callable[[httpx.Request], httpx.Response], **kw: Any) -> IngvClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return IngvClient(http, sleep=_no_sleep, **kw)


async def test_events() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_COLLECTION)

    async with _client(handler) as c:
        events = await c.events(_START, _END, min_magnitude=3.5)
    assert [e.id for e in events] == ["47606532"]
    assert seen[0].url.params["starttime"] == "2026-10-23T00:00:00"
    assert seen[0].url.params["minmagnitude"] == "3.5"


async def test_empty_window_is_204() -> None:
    async with _client(lambda _: httpx.Response(204)) as c:
        assert await c.events(_START, _END) == []


@pytest.mark.parametrize(
    "response",
    [httpx.Response(400, text="bad"), httpx.Response(200, text="<html>")],
)
async def test_event_service_errors_raise(response: httpx.Response) -> None:
    async with _client(lambda _: response) as c:
        with pytest.raises(IngvError):
            await c.events(_START, _END)


async def test_shakemap() -> None:
    xml = make_grid_xml()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/data/47606532/current/products/grid.xml"
        return httpx.Response(200, content=xml)

    async with _client(handler) as c:
        grid = await c.shakemap(47606532)
    assert grid is not None and grid.pga_g(14.03, 38.98) == pytest.approx(0.23)


async def test_no_shakemap_is_404() -> None:
    async with _client(lambda _: httpx.Response(404)) as c:
        assert await c.shakemap("1") is None


async def test_shakemap_other_errors_raise() -> None:
    async with _client(lambda _: httpx.Response(403)) as c:
        with pytest.raises(IngvError, match="HTTP 403"):
            await c.shakemap_xml("1")


async def test_retries_5xx_then_succeeds() -> None:
    calls = iter([httpx.Response(503), httpx.Response(429), httpx.Response(200, json=_COLLECTION)])
    async with _client(lambda _: next(calls), retries=3) as c:
        assert len(await c.events(_START, _END)) == 1


async def test_gives_up_after_retries_and_an_empty_5xx_is_not_a_quiet_week() -> None:
    async with _client(lambda _: httpx.Response(503), retries=1) as c:
        with pytest.raises(IngvError, match="HTTP 503"):
            await c.events(_START, _END)


async def test_transport_errors_are_retried_then_raised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with _client(handler, retries=2) as c:
        with pytest.raises(IngvError, match="down"):
            await c.events(_START, _END)


async def test_send_hook_replaces_transport_and_retries() -> None:
    calls: list[tuple[str, str]] = []

    async def send(method: str, url: str, **kwargs: Any) -> httpx.Response:
        calls.append((method, url))
        return httpx.Response(503)

    c = IngvClient(send=send, retries=5)
    with pytest.raises(IngvError, match="HTTP 503"):
        await c.events(_START, _END)
    assert len(calls) == 1
    await c.aclose()


async def test_owns_and_closes_its_client() -> None:
    c = IngvClient()
    await c.aclose()
    assert c._client is not None and c._client.is_closed


async def test_updated_after_is_sent() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    async with _client(handler) as c:
        await c.events(_START, _END, updated_after=_START + timedelta(hours=10))
    assert seen[0].url.params["updatedafter"] == "2026-10-23T10:00:00"


async def test_products_info_stations_uncertainty() -> None:
    data = Path(__file__).parent / "data"
    files = {
        "info.json": (data / "info_47606532.json").read_bytes(),
        "stationlist.json": (data / "stationlist_47606532.json").read_bytes(),
        "uncertainty.xml": make_grid_xml(),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.path.rsplit("/", 1)[-1]
        assert request.url.path == f"/data/47606532/current/products/{name}"
        return httpx.Response(200, content=files[name]) if name in files else httpx.Response(404)

    async with _client(handler) as c:
        info = await c.info(47606532)
        stations = await c.stations(47606532)
        unc = await c.uncertainty(47606532)
        assert await c.product(47606532, "rupture.json") is None
    assert info is not None and info.version == 4
    assert stations is not None and len(stations) == 3
    assert unc is not None and unc.nlon == 4


async def test_missing_products_are_none() -> None:
    async with _client(lambda _: httpx.Response(404)) as c:
        assert await c.info(1) is None
        assert await c.stations(1) is None
        assert await c.uncertainty(1) is None


@pytest.mark.parametrize("body", [b"<html>", b"[1, 2]"])
async def test_product_json_that_is_not_an_object_raises(body: bytes) -> None:
    async with _client(lambda _: httpx.Response(200, content=body)) as c:
        with pytest.raises(IngvError, match=r"info\.json"):
            await c.info(1)


async def test_product_errors_raise() -> None:
    async with _client(lambda _: httpx.Response(500)) as c:
        with pytest.raises(IngvError, match=r"stationlist\.json: HTTP 500"):
            await c.stations(1)
