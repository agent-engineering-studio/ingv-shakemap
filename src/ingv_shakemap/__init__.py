"""ingv-shakemap: INGV earthquakes and ShakeMap ground shaking, from Python."""

from importlib.metadata import version

from ingv_shakemap.client import IngvClient
from ingv_shakemap.errors import GridError, IngvError
from ingv_shakemap.events import (
    FDSN_EVENT_URL,
    ITALY,
    Event,
    event_query,
    parse_events,
    shakemap_grid_url,
    shakemap_product_url,
)
from ingv_shakemap.grid import GridEvent, GridField, ShakeGrid, parse_grid
from ingv_shakemap.products import (
    GroundMotionSummary,
    MapRun,
    ShakeMapInfo,
    Station,
    parse_info,
    parse_stations,
)

__version__ = version("ingv-shakemap")

__all__ = [
    "FDSN_EVENT_URL",
    "ITALY",
    "Event",
    "GridError",
    "GridEvent",
    "GridField",
    "GroundMotionSummary",
    "IngvClient",
    "IngvError",
    "MapRun",
    "ShakeGrid",
    "ShakeMapInfo",
    "Station",
    "__version__",
    "event_query",
    "parse_events",
    "parse_grid",
    "parse_info",
    "parse_stations",
    "shakemap_grid_url",
    "shakemap_product_url",
]
