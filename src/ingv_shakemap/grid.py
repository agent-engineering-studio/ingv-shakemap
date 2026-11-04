"""A ShakeMap ``grid.xml``, read into numbers you can sample at any point.

Pure: nothing here does I/O.

The format (ShakeMap 4, checked on INGV files in October and November 2026):

* a root ``<shakemap_grid>`` with the map's version and ``map_status``
  (``automatic`` until a seismologist reviews it);
* an ``<event>`` with magnitude, depth, epicentre and time;
* a ``<grid_specification>`` with the extent, ``nlon`` and ``nlat``. The step
  changes from event to event (about 90 m at Campi Flegrei, 0.0083° ≈ 900 m
  elsewhere);
* one ``<grid_field>`` per column (``LON``, ``LAT``, ``MMI``, ``PGA``, ``PGV``,
  ``PSA03``, ``PSA10``, ``PSA30``, ``SVEL``), each with its unit;
* a ``<grid_data>`` of ``nlon * nlat`` rows, **from the north edge southwards,
  longitude fastest**.

Two traps. PGA and the PSA columns are in **percent of g**, not in g: 0.11 is
a barely felt 0.0011 g. And the row order is a convention of the format, not
something the file states, so :func:`parse_grid` checks it on the first rows
instead of assuming it: a different order would move every value.

A big event's grid is 10-12 MB of text; parsing it takes a few hundred
milliseconds, so call :func:`parse_grid` in a thread from async code.
"""

from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal

import numpy as np
import numpy.typing as npt

from ingv_shakemap.errors import GridError

_NS = re.compile(r"\{[^}]*\}")

#: The units ShakeMap writes for a percentage of g.
PERCENT_G: Final = frozenset({"%g", "pctg"})


@dataclass(frozen=True, slots=True)
class GridField:
    """One column of the grid."""

    name: str
    units: str
    index: int


@dataclass(frozen=True, slots=True)
class GridEvent:
    """The earthquake a grid is about, as the grid itself describes it."""

    id: str
    magnitude: float | None
    depth_km: float | None
    longitude: float | None
    latitude: float | None
    time: datetime | None
    description: str | None


@dataclass(frozen=True, slots=True)
class ShakeGrid:
    """The ground shaking of one event on a regular lon/lat grid."""

    event: GridEvent
    #: ``automatic`` or ``RELEASED``/``reviewed``, as ShakeMap writes it.
    map_status: str | None
    version: str | None
    process_time: datetime | None
    lon_min: float
    lat_max: float
    lon_step: float
    lat_step: float
    nlon: int
    nlat: int
    fields: dict[str, GridField]
    #: Every column, ``(nlat, nlon, len(fields))``, north row first, native units.
    values: npt.NDArray[np.float64] = field(repr=False)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """West, south, east, north of the grid's points."""
        lon_max = self.lon_min + (self.nlon - 1) * self.lon_step
        lat_min = self.lat_max - (self.nlat - 1) * self.lat_step
        return (self.lon_min, lat_min, lon_max, self.lat_max)

    def _index(self, longitude: float, latitude: float) -> tuple[int, int] | None:
        col = round((longitude - self.lon_min) / self.lon_step)
        row = round((self.lat_max - latitude) / self.lat_step)
        if not (0 <= col < self.nlon and 0 <= row < self.nlat):
            return None
        return row, col

    def value_at(self, name: str, longitude: float, latitude: float) -> float | None:
        """Column ``name`` at the grid point nearest to a position, in its native unit.

        ``None`` outside the grid. Raises :class:`GridError` for a column the
        grid does not have.
        """
        if name not in self.fields:
            raise GridError(f"no {name!r} column; the grid has {', '.join(self.fields)}")
        at = self._index(longitude, latitude)
        if at is None:
            return None
        return float(self.values[at[0], at[1], self.fields[name].index])

    def pga_g(self, longitude: float, latitude: float) -> float | None:
        """Peak ground acceleration at a position, in **g** (not percent of g)."""
        return self._in_g("PGA", longitude, latitude)

    def pgv_cm_s(self, longitude: float, latitude: float) -> float | None:
        """Peak ground velocity at a position, in cm/s."""
        return self.value_at("PGV", longitude, latitude)

    def mmi(self, longitude: float, latitude: float) -> float | None:
        """Macroseismic intensity at a position (Modified Mercalli)."""
        return self.value_at("MMI", longitude, latitude)

    def _in_g(self, name: str, longitude: float, latitude: float) -> float | None:
        value = self.value_at(name, longitude, latitude)
        if value is None:
            return None
        return value / self._g_divisor(name)

    def column(self, name: str) -> npt.NDArray[np.float64]:
        """Column ``name`` as an ``(nlat, nlon)`` array, north row first, native unit."""
        if name not in self.fields:
            raise GridError(f"no {name!r} column; the grid has {', '.join(self.fields)}")
        return self.values[:, :, self.fields[name].index]

    def sample(
        self,
        name: str,
        longitudes: npt.ArrayLike,
        latitudes: npt.ArrayLike,
        *,
        method: Literal["nearest", "bilinear"] = "nearest",
    ) -> npt.NDArray[np.float64]:
        """Column ``name`` at many positions at once, in its native unit.

        ``nearest`` gives exactly what :meth:`value_at` gives, point by point
        (ties round half to even, as Python's ``round``). ``bilinear``
        interpolates between the four surrounding grid points and is defined
        only inside :attr:`bbox`. Positions outside the grid are ``NaN``.
        """
        grid = self.column(name)
        lon = np.asarray(longitudes, dtype=float)
        lat = np.asarray(latitudes, dtype=float)
        lon, lat = np.broadcast_arrays(lon, lat)
        x = (lon - self.lon_min) / self.lon_step
        y = (self.lat_max - lat) / self.lat_step
        out = np.full(lon.shape, np.nan)
        if method == "nearest":
            col, row = np.rint(x), np.rint(y)
            inside = (col >= 0) & (col < self.nlon) & (row >= 0) & (row < self.nlat)
            out[inside] = grid[row[inside].astype(int), col[inside].astype(int)]
            return out
        if method != "bilinear":
            raise GridError(f"unknown method {method!r}: nearest or bilinear")
        eps = 1e-9
        inside = (x >= -eps) & (x <= self.nlon - 1 + eps) & (y >= -eps) & (y <= self.nlat - 1 + eps)
        xi, yi = x[inside], y[inside]
        c0 = np.clip(np.floor(xi), 0, self.nlon - 2).astype(int)
        r0 = np.clip(np.floor(yi), 0, self.nlat - 2).astype(int)
        tx = np.clip(xi - c0, 0.0, 1.0)
        ty = np.clip(yi - r0, 0.0, 1.0)
        top = grid[r0, c0] * (1 - tx) + grid[r0, c0 + 1] * tx
        bottom = grid[r0 + 1, c0] * (1 - tx) + grid[r0 + 1, c0 + 1] * tx
        out[inside] = top * (1 - ty) + bottom * ty
        return out

    def sample_g(
        self,
        name: str,
        longitudes: npt.ArrayLike,
        latitudes: npt.ArrayLike,
        *,
        method: Literal["nearest", "bilinear"] = "nearest",
    ) -> npt.NDArray[np.float64]:
        """An acceleration column (``PGA``, ``PSA03``...) at many positions, in **g**."""
        return self.sample(name, longitudes, latitudes, method=method) / self._g_divisor(name)

    def _g_divisor(self, name: str) -> float:
        units = self.fields[name].units
        if units in PERCENT_G:
            return 100.0
        if units == "g":
            return 1.0
        raise GridError(f"{name} in {units!r}: expected percent of g or g")


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def parse_grid(xml: bytes | str) -> ShakeGrid:
    """A ``grid.xml`` as a :class:`ShakeGrid`; raises only :class:`GridError`."""
    try:
        return _parse(xml.encode() if isinstance(xml, str) else xml)
    except GridError:
        raise
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise GridError(f"unreadable grid: {exc}") from exc


def _parse(xml: bytes) -> ShakeGrid:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise GridError("not valid XML") from exc
    children: dict[str, Any] = {}
    columns: list[GridField] = []
    for el in root:
        tag = _NS.sub("", el.tag)
        if tag == "grid_field":
            columns.append(
                GridField(el.get("name", ""), el.get("units", ""), int(el.get("index", "0")) - 1)
            )
        else:
            children.setdefault(tag, el)
    spec, data = children.get("grid_specification"), children.get("grid_data")
    if spec is None or data is None or not (data.text or "").strip():
        raise GridError("no grid_specification or grid_data")
    fields = {c.name: c for c in columns}
    if "LON" not in fields or "LAT" not in fields:
        raise GridError("no LON or LAT column")
    nlon, nlat = int(spec.get("nlon", "")), int(spec.get("nlat", ""))
    lon_min, lon_max = float(spec.get("lon_min", "")), float(spec.get("lon_max", ""))
    lat_min, lat_max = float(spec.get("lat_min", "")), float(spec.get("lat_max", ""))
    if (
        nlon < 2
        or nlat < 2
        or not all(math.isfinite(v) for v in (lon_min, lon_max, lat_min, lat_max))
    ):
        raise GridError("invalid grid_specification")

    rows = np.loadtxt(io.StringIO(data.text), dtype=float, ndmin=2)
    if rows.shape[0] != nlon * nlat:
        raise GridError(f"{rows.shape[0]} rows, expected {nlon * nlat}")
    if rows.shape[1] < len(columns) or max(c.index for c in columns) >= rows.shape[1]:
        raise GridError(f"{rows.shape[1]} columns in grid_data, the header declares more")
    lon_step = (lon_max - lon_min) / (nlon - 1)
    lat_step = (lat_max - lat_min) / (nlat - 1)
    i_lon, i_lat = fields["LON"].index, fields["LAT"].index
    if not (
        math.isclose(rows[0, i_lon], lon_min, abs_tol=lon_step / 2)
        and math.isclose(rows[0, i_lat], lat_max, abs_tol=lat_step / 2)
        and math.isclose(rows[1, i_lon], lon_min + lon_step, abs_tol=lon_step / 2)
    ):
        raise GridError("rows are not north to south, west to east")

    ev = children.get("event")
    event = GridEvent(
        id=str(root.get("event_id") or (ev.get("event_id") if ev is not None else "") or ""),
        magnitude=_float(ev.get("magnitude")) if ev is not None else None,
        depth_km=_float(ev.get("depth")) if ev is not None else None,
        longitude=_float(ev.get("lon")) if ev is not None else None,
        latitude=_float(ev.get("lat")) if ev is not None else None,
        time=_time(ev.get("event_timestamp")) if ev is not None else None,
        description=ev.get("event_description") if ev is not None else None,
    )
    return ShakeGrid(
        event=event,
        map_status=root.get("map_status"),
        version=root.get("shakemap_version"),
        process_time=_time(root.get("process_timestamp")),
        lon_min=lon_min,
        lat_max=lat_max,
        lon_step=lon_step,
        lat_step=lat_step,
        nlon=nlon,
        nlat=nlat,
        fields=fields,
        values=rows.reshape(nlat, nlon, rows.shape[1]),
    )


__all__ = ["PERCENT_G", "GridError", "GridEvent", "GridField", "ShakeGrid", "parse_grid"]
