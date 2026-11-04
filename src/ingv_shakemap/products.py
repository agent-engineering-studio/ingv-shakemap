"""The other products of a ShakeMap: ``info.json`` and ``stationlist.json``.

Pure: nothing here does I/O.

``info.json`` weighs a few kB against the 10-12 MB of ``grid.xml`` and says
everything you need to decide whether to download the grid again: the map's
version, its status, the history of its runs, the ground-motion model and how
many stations constrained it. The maps of the 23 October 2026 sequence went
through four versions in forty hours, the last one two days after the
earthquake (checked on 4 November 2026).

``stationlist.json`` is the stations behind the map: what each one recorded
and what the model predicted there. Two habits of the INGV file:

* a missing amplitude is the **string** ``"null"``, not JSON ``null``: 263
  of 469 stations of event 47606532 have ``"pga": "null"``;
* the station's ``pga`` is in **percent of g**, like the grid's, even though
  the property itself carries no unit (its channels say ``%g``).

``uncertainty.xml`` needs no parser of its own: it is a ``grid.xml`` whose
columns are ``STDPGA`` (in ln g), ``STDPGV``, ``STDMMI``... so
:func:`ingv_shakemap.parse_grid` reads it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ingv_shakemap.errors import IngvError


@dataclass(frozen=True, slots=True)
class MapRun:
    """One run of a ShakeMap, from ``info.json``'s ``map_data_history``."""

    time: datetime | None
    source: str | None
    version: int | None
    comment: str | None


@dataclass(frozen=True, slots=True)
class GroundMotionSummary:
    """The peak of one intensity measure, as ``info.json`` summarises it."""

    units: str | None
    #: Highest value on the grid.
    max_grid: float | None
    #: Highest value at a station.
    max_observed: float | None
    #: Bias of the model against the stations (natural log).
    bias: float | None


@dataclass(frozen=True, slots=True)
class ShakeMapInfo:
    """What ``info.json`` says about a map: enough to tell whether it changed."""

    event_id: str
    #: The map's version; it grows with every run.
    version: int | None
    #: ``automatic`` until a seismologist reviews it.
    map_status: str | None
    process_time: datetime | None
    history: tuple[MapRun, ...]
    seismic_stations: int | None
    intensity_observations: int | None
    #: The ground-motion model, e.g. ``gmpe_47606532_custom``.
    gmpe: str | None
    #: The GMPEs it is made of, per intensity measure: ``{"PGA": ("BindiEtAl2011",)}``.
    gmpes: dict[str, tuple[str, ...]]
    ground_motions: dict[str, GroundMotionSummary]
    #: Station amplitudes the map discarded as outliers or glitches.
    flagged_stations: int | None
    #: The whole document, as INGV sent it.
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True, slots=True)
class Station:
    """One station of ``stationlist.json``, with what it recorded."""

    id: str
    network: str | None
    code: str | None
    name: str | None
    source: str | None
    #: ``seismic`` for an instrument, ``macroseismic`` for felt reports.
    station_type: str | None
    longitude: float
    latitude: float
    #: Recorded peak ground acceleration in **g**; ``None`` when not usable.
    pga_g: float | None
    #: Recorded peak ground velocity in cm/s.
    pgv_cm_s: float | None
    intensity: float | None
    #: What the ground-motion model predicted here, in g.
    predicted_pga_g: float | None
    #: Hypocentral distance in km.
    distance_km: float | None
    vs30_m_s: float | None
    #: Every property of the feature, as INGV sent it.
    properties: dict[str, Any] = field(default_factory=dict, repr=False)


def _num(value: Any) -> float | None:
    """A number, or ``None`` for JSON null, the string ``"null"`` or anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _int(value: Any) -> int | None:
    number = _num(value)
    return int(number) if number is not None and number.is_integer() else None


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _gmpe_names(spec: Any) -> tuple[str, ...]:
    """The leaf GMPEs of a nested ``multigmpe`` entry, without the brackets."""
    names: list[str] = []
    for item in _dict(spec).get("gmpes") or []:
        if isinstance(item, str):
            names.append(item.strip("[]"))
        else:
            names.extend(_gmpe_names(item))
    return tuple(names)


def parse_info(payload: dict[str, Any]) -> ShakeMapInfo:
    """``info.json`` as a :class:`ShakeMapInfo`; raises :class:`IngvError` if it is not one."""
    if not isinstance(payload, dict) or "output" not in payload:
        raise IngvError("not a ShakeMap info.json")
    event = _dict(_dict(payload.get("input")).get("event_information"))
    processing = _dict(payload.get("processing"))
    versions = _dict(processing.get("shakemap_versions"))
    history = tuple(
        MapRun(
            time=_time(run[0]) if len(run) > 0 else None,
            source=_str(run[1]) if len(run) > 1 else None,
            version=_int(run[2]) if len(run) > 2 else None,
            comment=_str(run[3]) if len(run) > 3 else None,
        )
        for run in versions.get("map_data_history") or []
        if isinstance(run, list)
    )
    output = _dict(payload.get("output"))
    motions = {
        name: GroundMotionSummary(
            units=_str(_dict(m).get("units")),
            max_grid=_num(_dict(m).get("max_grid")),
            max_observed=_num(_dict(m).get("max")),
            bias=_num(_dict(m).get("bias")),
        )
        for name, m in _dict(output.get("ground_motions")).items()
    }
    gmpe = _dict(_dict(processing.get("ground_motion_modules")).get("gmpe")).get("module")
    return ShakeMapInfo(
        event_id=str(event.get("event_id") or event.get("id") or ""),
        version=_int(versions.get("map_version")),
        map_status=_str(versions.get("map_status")),
        process_time=_time(versions.get("process_time")),
        history=history,
        seismic_stations=_int(event.get("seismic_stations")),
        intensity_observations=_int(event.get("intensity_observations")),
        gmpe=_str(gmpe),
        gmpes={imt: _gmpe_names(s) for imt, s in _dict(payload.get("multigmpe")).items()},
        ground_motions=motions,
        flagged_stations=_int(_dict(output.get("uncertainty")).get("total_flagged_pgm")),
        raw=payload,
    )


def _predicted(props: dict[str, Any], name: str) -> float | None:
    for p in props.get("predictions") or []:
        if isinstance(p, dict) and p.get("name") == name and p.get("units") == "%g":
            value = _num(p.get("value"))
            return None if value is None else value / 100.0
    return None


def parse_station(feature: dict[str, Any]) -> Station | None:
    """One feature of ``stationlist.json``; ``None`` without an id or a position."""
    props = _dict(feature.get("properties"))
    coords = _dict(feature.get("geometry")).get("coordinates") or []
    raw_id = feature.get("id")
    if not raw_id or len(coords) < 2:
        return None
    lon, lat = _num(coords[0]), _num(coords[1])
    if lon is None or lat is None:
        return None
    pga = _num(props.get("pga"))
    return Station(
        id=str(raw_id),
        network=_str(props.get("network")),
        code=_str(props.get("code")),
        name=_str(props.get("name")),
        source=_str(props.get("source")),
        station_type=_str(props.get("station_type")),
        longitude=lon,
        latitude=lat,
        pga_g=None if pga is None else pga / 100.0,
        pgv_cm_s=_num(props.get("pgv")),
        intensity=_num(props.get("intensity")),
        predicted_pga_g=_predicted(props, "pga"),
        distance_km=_num(props.get("distance")),
        vs30_m_s=_num(props.get("vs30")),
        properties=props,
    )


def parse_stations(payload: dict[str, Any]) -> list[Station]:
    """The stations of ``stationlist.json``, skipping features that cannot be read."""
    features = payload.get("features") if isinstance(payload, dict) else None
    if not isinstance(features, list):
        raise IngvError("not a ShakeMap stationlist.json")
    return [s for f in features if isinstance(f, dict) and (s := parse_station(f)) is not None]


__all__ = [
    "GroundMotionSummary",
    "MapRun",
    "ShakeMapInfo",
    "Station",
    "parse_info",
    "parse_station",
    "parse_stations",
]
