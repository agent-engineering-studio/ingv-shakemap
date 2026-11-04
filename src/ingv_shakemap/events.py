"""Earthquakes from the INGV FDSN event service: the query and its GeoJSON answer.

Pure: nothing here does I/O.

``https://webservices.ingv.it/fdsnws/event/1/query`` follows the FDSN event
standard. Three habits of the INGV service matter:

* times go in and come out in **UTC without an offset** (``2026-10-23T10:19:15``);
* an empty window answers **204 No Content**, not an empty collection;
* the GeoJSON feature has no top-level ``id``: the event id is
  ``properties.eventId``, an integer, and it is the id ShakeMap uses too.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

from ingv_shakemap.errors import IngvError

FDSN_EVENT_URL: Final = "https://webservices.ingv.it/fdsnws/event/1/query"
SHAKEMAP_BASE: Final = "https://shakemap.ingv.it/data"

#: West, south, east, north in degrees.
BBox = tuple[float, float, float, float]

#: Italy and its seas, the area INGV locates routinely.
ITALY: Final[BBox] = (6.0, 35.0, 19.0, 47.5)


@dataclass(frozen=True, slots=True)
class Event:
    """One earthquake of the INGV catalogue."""

    id: str
    time: datetime
    magnitude: float
    magnitude_type: str | None
    longitude: float
    latitude: float
    #: Kilometres below the surface; ``None`` when the catalogue gives none.
    depth_km: float | None
    place: str | None
    #: Every property of the GeoJSON feature, as INGV sent it.
    properties: dict[str, Any] = field(default_factory=dict, repr=False)


def fdsn_time(at: datetime) -> str:
    """``at`` as the FDSN service wants it: UTC, no offset, whole seconds."""
    if at.tzinfo is None:
        raise IngvError("naive datetime: pass an aware one")
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")


def event_query(
    start: datetime,
    end: datetime,
    *,
    bbox: BBox = ITALY,
    min_magnitude: float | None = None,
    max_depth_km: float | None = None,
    limit: int | None = None,
    updated_after: datetime | None = None,
) -> dict[str, str]:
    """Query parameters for the events in ``bbox`` between ``start`` and ``end``, newest first.

    ``updated_after`` keeps only the events created or revised after that
    instant (the FDSN ``updatedafter``): a sync that runs every hour asks for
    what changed since the last run instead of the whole window again.
    """
    if end <= start:
        raise IngvError("end must come after start")
    west, south, east, north = bbox
    params = {
        "format": "geojson",
        "starttime": fdsn_time(start),
        "endtime": fdsn_time(end),
        "minlatitude": str(south),
        "maxlatitude": str(north),
        "minlongitude": str(west),
        "maxlongitude": str(east),
        "orderby": "time",
    }
    if min_magnitude is not None:
        params["minmagnitude"] = str(min_magnitude)
    if max_depth_km is not None:
        params["maxdepth"] = str(max_depth_km)
    if limit is not None:
        params["limit"] = str(limit)
    if updated_after is not None:
        params["updatedafter"] = fdsn_time(updated_after)
    return params


def shakemap_product_url(event_id: str | int, product: str, *, base: str = SHAKEMAP_BASE) -> str:
    """URL of one product of the current ShakeMap of an event.

    ``product`` is a file name: ``grid.xml``, ``uncertainty.xml``,
    ``info.json``, ``stationlist.json``. The older ``/shake4/`` prefix answers
    404 for every event (checked on 19 October 2026).
    """
    return f"{base}/{event_id}/current/products/{product}"


def shakemap_grid_url(event_id: str | int, *, base: str = SHAKEMAP_BASE) -> str:
    """URL of the current ``grid.xml`` of an event."""
    return shakemap_product_url(event_id, "grid.xml", base=base)


def parse_event(feature: dict[str, Any]) -> Event | None:
    """One GeoJSON feature as an :class:`Event`.

    ``None`` when it lacks the id, the position, the time or the magnitude.
    """
    props = dict(feature.get("properties") or {})
    coords = (feature.get("geometry") or {}).get("coordinates") or []
    raw_id = feature.get("id") or props.get("eventId") or props.get("eventID")
    time_text = props.get("time")
    mag = props.get("mag")
    if raw_id in (None, "") or len(coords) < 2 or not time_text or mag is None:
        return None
    try:
        time = datetime.fromisoformat(str(time_text).replace("Z", "+00:00"))
        depth = coords[2] if len(coords) > 2 else None
        return Event(
            id=str(raw_id),
            time=time if time.tzinfo else time.replace(tzinfo=UTC),
            magnitude=float(mag),
            magnitude_type=props.get("magType"),
            longitude=float(coords[0]),
            latitude=float(coords[1]),
            depth_km=float(depth) if depth is not None else None,
            place=props.get("place"),
            properties=props,
        )
    except (TypeError, ValueError):
        return None


def parse_events(payload: dict[str, Any]) -> list[Event]:
    """The events of a GeoJSON answer, skipping features that cannot be read."""
    features = payload.get("features")
    if not isinstance(features, list):
        raise IngvError("not a GeoJSON FeatureCollection")
    return [e for f in features if isinstance(f, dict) and (e := parse_event(f)) is not None]


__all__ = [
    "FDSN_EVENT_URL",
    "ITALY",
    "SHAKEMAP_BASE",
    "BBox",
    "Event",
    "event_query",
    "fdsn_time",
    "parse_event",
    "parse_events",
    "shakemap_grid_url",
    "shakemap_product_url",
]
