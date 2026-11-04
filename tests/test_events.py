from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from ingv_shakemap import (
    Event,
    IngvError,
    event_query,
    parse_events,
    shakemap_grid_url,
    shakemap_product_url,
)
from ingv_shakemap.events import fdsn_time, parse_event

# A feature as the INGV service sent it on 2026-11-04: no top-level id.
_FEATURE = {
    "type": "Feature",
    "properties": {
        "eventId": 47606532,
        "time": "2026-10-23T10:19:15.470000",
        "magType": "Mw",
        "mag": 5.5,
        "place": "Tirreno Meridionale [Mare]",
        "type": "earthquake",
    },
    "geometry": {"type": "Point", "coordinates": [14.1717, 38.7938, 8.8]},
}


def test_query_parameters() -> None:
    start = datetime(2026, 10, 23, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    params = event_query(start, start + timedelta(days=1), min_magnitude=3.5, max_depth_km=30,
                         limit=10)  # fmt: skip
    assert params == {
        "format": "geojson",
        "starttime": "2026-10-23T10:00:00",
        "endtime": "2026-10-24T10:00:00",
        "minlatitude": "35.0",
        "maxlatitude": "47.5",
        "minlongitude": "6.0",
        "maxlongitude": "19.0",
        "orderby": "time",
        "minmagnitude": "3.5",
        "maxdepth": "30",
        "limit": "10",
    }


def test_query_refuses_naive_times_and_empty_windows() -> None:
    t = datetime(2026, 10, 23, tzinfo=UTC)
    with pytest.raises(IngvError, match="naive"):
        fdsn_time(datetime(2026, 10, 23))
    with pytest.raises(IngvError, match="after start"):
        event_query(t, t)


def test_shakemap_url() -> None:
    assert (
        shakemap_grid_url(47606532)
        == "https://shakemap.ingv.it/data/47606532/current/products/grid.xml"
    )


def test_parse_event_uses_properties_event_id_and_utc() -> None:
    e = parse_event(_FEATURE)
    assert e == Event(
        id="47606532",
        time=datetime(2026, 10, 23, 10, 19, 15, 470000, tzinfo=UTC),
        magnitude=5.5,
        magnitude_type="Mw",
        longitude=14.1717,
        latitude=38.7938,
        depth_km=8.8,
        place="Tirreno Meridionale [Mare]",
        properties=_FEATURE["properties"],  # type: ignore[arg-type]
    )


_AT = "2026-10-23T10:19:15"
_XY = {"coordinates": [1, 2]}


@pytest.mark.parametrize(
    "broken",
    [
        {"properties": {"time": _AT, "mag": 4}, "geometry": _XY},
        {"properties": {"eventId": 1, "mag": 4}, "geometry": _XY},
        {"properties": {"eventId": 1, "time": _AT}, "geometry": _XY},
        {"properties": {"eventId": 1, "time": _AT, "mag": 4}, "geometry": {}},
        {"properties": {"eventId": 1, "time": "yesterday", "mag": 4}, "geometry": _XY},
    ],
)
def test_unreadable_features_are_skipped(broken: dict[str, object]) -> None:
    assert parse_event(broken) is None


def test_depth_optional_and_offsets_kept() -> None:
    f = {"id": "x1", "properties": {"time": "2026-10-23T10:19:15Z", "mag": "3.1"},
         "geometry": {"coordinates": [14, 38]}}  # fmt: skip
    e = parse_event(f)
    assert e is not None and e.id == "x1" and e.depth_km is None and e.time.tzinfo is not None


def test_parse_events() -> None:
    events = parse_events({"type": "FeatureCollection", "features": [_FEATURE, {"bad": 1}, "x"]})
    assert [e.id for e in events] == ["47606532"]
    with pytest.raises(IngvError, match="FeatureCollection"):
        parse_events({"error": "boom"})


def test_product_url() -> None:
    assert shakemap_product_url(1, "info.json") == (
        "https://shakemap.ingv.it/data/1/current/products/info.json"
    )
