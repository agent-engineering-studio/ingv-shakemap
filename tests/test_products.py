from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ingv_shakemap import IngvError, parse_info, parse_stations
from ingv_shakemap.products import parse_station

_DATA = Path(__file__).parent / "data"


def _load(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((_DATA / name).read_text())
    return payload


def test_info_of_a_real_map() -> None:
    info = parse_info(_load("info_47606532.json"))
    assert info.event_id == "47606532"
    assert info.version == 4 and info.map_status == "automatic"
    assert info.process_time == datetime(2026, 10, 25, 2, 6, 23, tzinfo=UTC)
    assert [r.version for r in info.history] == [1, 2, 3, 4]
    # The fourth run came about forty hours after the earthquake.
    assert info.history[-1].time == datetime(2026, 10, 25, 2, 5, 54, tzinfo=UTC)
    assert info.history[0].source == "IV" and info.history[0].comment == "SM4 run"
    assert info.seismic_stations == 469 and info.intensity_observations == 0
    assert info.gmpe == "gmpe_47606532_custom"
    assert info.gmpes["PGA"] == ("BindiEtAl2011",)
    pga = info.ground_motions["PGA"]
    assert (pga.units, pga.max_grid, pga.max_observed, pga.bias) == ("g", 0.33, 0.057, -0.019)
    assert info.flagged_stations == 299


def test_info_tolerates_missing_sections() -> None:
    versions: dict[str, Any] = {"map_data_history": [[]]}
    info = parse_info({"output": {}, "processing": {"shakemap_versions": versions}})
    assert info.event_id == "" and info.version is None and info.gmpe is None
    assert info.history[0].time is None and info.ground_motions == {}


@pytest.mark.parametrize("payload", [{}, {"input": {}}, []])
def test_info_that_is_not_one(payload: Any) -> None:
    with pytest.raises(IngvError):
        parse_info(payload)


def test_stations_of_a_real_map() -> None:
    stations = parse_stations(_load("stationlist_47606532.json"))
    assert [s.id for s in stations] == ["IT.CFL", "IT.ISNL", "IV.STRE"]
    cfl = stations[0]
    assert (cfl.network, cfl.code, cfl.station_type) == ("IT", "CFL", "seismic")
    assert (cfl.longitude, cfl.latitude) == (14.0232, 38.037)
    # Percent of g in the file, g here.
    assert cfl.pga_g == pytest.approx(0.001948)
    assert cfl.predicted_pga_g == pytest.approx(0.007096)
    assert (cfl.pgv_cm_s, cfl.intensity, cfl.distance_km, cfl.vs30_m_s) == (
        0.2478,
        3.3,
        85.595,
        523.86,
    )


def test_the_string_null_is_no_value() -> None:
    stre = parse_stations(_load("stationlist_47606532.json"))[2]
    assert stre.pga_g is None and stre.pgv_cm_s is None and stre.intensity is None
    assert stre.distance_km == 90.867


@pytest.mark.parametrize(
    "feature",
    [
        {"geometry": {"coordinates": [14.0, 38.0]}},
        {"id": "X", "geometry": {"coordinates": [14.0]}},
        {"id": "X", "geometry": {"coordinates": ["a", 38.0]}},
    ],
)
def test_unreadable_station_is_skipped(feature: dict[str, Any]) -> None:
    assert parse_station(feature) is None


def test_station_values_of_odd_types() -> None:
    s = parse_station(
        {
            "id": "X",
            "geometry": {"coordinates": [14, 38]},
            "properties": {
                "pga": True,
                "pgv": "1.5",
                "intensity": [3],
                "predictions": ["x", {"name": "pga", "units": "g", "value": 1}],
            },
        }
    )
    assert s is not None
    assert s.pga_g is None and s.pgv_cm_s == 1.5 and s.intensity is None
    assert s.predicted_pga_g is None


def test_prediction_without_value() -> None:
    s = parse_station(
        {
            "id": "X",
            "geometry": {"coordinates": [14, 38]},
            "properties": {"predictions": [{"name": "pga", "units": "%g", "value": "null"}]},
        }
    )
    assert s is not None and s.predicted_pga_g is None


@pytest.mark.parametrize("payload", [{}, {"features": {}}, []])
def test_stationlist_that_is_not_one(payload: Any) -> None:
    with pytest.raises(IngvError):
        parse_stations(payload)


def test_bad_times_and_versions() -> None:
    info = parse_info(
        {
            "output": {},
            "processing": {
                "shakemap_versions": {
                    "map_version": "4.5",
                    "process_time": "yesterday",
                    "map_data_history": [["2026-10-23T11:48:22", 7, "x", None], "junk"],
                }
            },
        }
    )
    assert info.version is None and info.process_time is None
    run = info.history[0]
    assert run.time == datetime(2026, 10, 23, 11, 48, 22, tzinfo=UTC)
    assert run.source is None and run.version is None and run.comment is None
    assert len(info.history) == 1
