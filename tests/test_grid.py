from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pytest
from conftest import make_grid_xml

from ingv_shakemap import GridError, parse_grid


def test_reads_header_event_and_columns() -> None:
    g = parse_grid(make_grid_xml())
    assert (g.nlon, g.nlat) == (4, 3)
    assert g.map_status == "automatic" and g.version == "4"
    assert g.process_time == datetime(2026, 10, 25, 2, 6, 34, tzinfo=UTC)
    assert g.event.id == "47606532" and g.event.magnitude == 5.5 and g.event.depth_km == 8.8
    assert g.event.time == datetime(2026, 10, 23, 10, 19, 15, tzinfo=UTC)
    assert list(g.fields) == ["LON", "LAT", "MMI", "PGA", "PGV"]
    assert g.bbox == pytest.approx((14.0, 38.98, 14.03, 39.0))
    assert g.column("PGA").shape == (3, 4)


def test_pga_is_converted_from_percent_of_g() -> None:
    g = parse_grid(make_grid_xml())
    # Row 2 (two steps south of the north edge), column 3: PGA = 23 %g.
    assert g.value_at("PGA", 14.03, 38.98) == 23
    assert g.pga_g(14.03, 38.98) == pytest.approx(0.23)
    assert g.mmi(14.0, 39.0) == 2
    assert g.pgv_cm_s(14.02, 39.0) == 2


def test_nearest_grid_point_and_outside() -> None:
    g = parse_grid(make_grid_xml())
    assert g.pga_g(14.0104, 38.9896) == pytest.approx(0.11)
    assert g.pga_g(14.5, 39.0) is None
    assert g.pga_g(14.0, 40.0) is None


def test_pga_already_in_g_and_unknown_units() -> None:
    assert parse_grid(make_grid_xml(pga_units="g")).pga_g(14.01, 39.0) == 1
    with pytest.raises(GridError, match="percent of g"):
        parse_grid(make_grid_xml(pga_units="m/s2")).pga_g(14.0, 39.0)


def test_unknown_column() -> None:
    g = parse_grid(make_grid_xml())
    with pytest.raises(GridError, match="no 'PSA10' column"):
        g.value_at("PSA10", 14.0, 39.0)
    with pytest.raises(GridError, match="no 'PSA10' column"):
        g.column("PSA10")


def test_accepts_text_and_a_grid_without_event() -> None:
    g = parse_grid(make_grid_xml(with_event=False).decode())
    assert g.event.id == "47606532" and g.event.magnitude is None and g.event.time is None


def test_refuses_rows_in_another_order() -> None:
    with pytest.raises(GridError, match="north to south"):
        parse_grid(make_grid_xml(order="south-first"))


@pytest.mark.parametrize(
    ("xml", "message"),
    [
        (b"<not xml", "not valid XML"),
        (b"<shakemap_grid></shakemap_grid>", "grid_specification or grid_data"),
        (make_grid_xml(rows_override=5), "5 rows, expected 12"),
        (make_grid_xml().replace(b'name="LON"', b'name="X"'), "LON or LAT"),
        (make_grid_xml().replace(b'nlon="4"', b'nlon="1"'), "invalid grid_specification"),
        (make_grid_xml().replace(b'nlon="4"', b'nlon="four"'), "unreadable grid"),
        (make_grid_xml().replace(b'index="5"', b'index="9"'), "header declares more"),
    ],
)
def test_bad_grids_raise_only_grid_error(xml: bytes, message: str) -> None:
    with pytest.raises(GridError, match=message):
        parse_grid(xml)


def test_grid_error_is_a_value_error() -> None:
    with pytest.raises(ValueError):
        parse_grid(b"<not xml")


def test_unreadable_event_attributes_become_none() -> None:
    xml = make_grid_xml().replace(b'magnitude="5.5"', b'magnitude="n/a"')
    xml = xml.replace(b'event_timestamp="2026-10-23T10:19:15"', b'event_timestamp="soon"')
    g = parse_grid(xml.replace(b'process_timestamp="2026-10-25T02:06:34"', b""))
    assert g.event.magnitude is None and g.event.time is None and g.process_time is None


def test_offset_timestamps_are_kept() -> None:
    xml = make_grid_xml().replace(b"2026-10-23T10:19:15", b"2026-10-23T10:19:15Z")
    assert parse_grid(xml).event.time == datetime(2026, 10, 23, 10, 19, 15, tzinfo=UTC)


def test_sample_nearest_matches_value_at_point_by_point() -> None:
    g = parse_grid(make_grid_xml(nlon=6, nlat=5))
    rng = np.random.default_rng(0)
    lons = rng.uniform(13.99, 14.06, 400)
    lats = rng.uniform(38.95, 39.01, 400)
    got = g.sample("PGA", lons, lats)
    for lon, lat, v in zip(lons, lats, got, strict=True):
        expected = g.value_at("PGA", float(lon), float(lat))
        assert (np.isnan(v) and expected is None) or v == expected


def test_sample_ties_round_half_to_even_like_round() -> None:
    g = parse_grid(make_grid_xml(step=0.5, lon_min=0.0, lat_max=10.0))
    # Half a step east of column 0 and of column 1: round() gives 0 and 2.
    assert list(g.sample("PGV", [0.25, 0.75], [10.0, 10.0])) == [0, 2]
    assert [g.pgv_cm_s(x, 10.0) for x in (0.25, 0.75)] == [0, 2]


def test_sample_bilinear() -> None:
    g = parse_grid(make_grid_xml())
    # PGA = 10*row + col is linear, so bilinear interpolation is exact.
    got = g.sample("PGA", [14.005, 14.03, 14.0], [38.995, 38.98, 39.0], method="bilinear")
    assert got == pytest.approx([5.5, 23.0, 0.0])
    outside = g.sample("PGA", [13.9999, 14.031, 14.01], [39.0, 38.98, 39.001], method="bilinear")
    assert np.isnan(outside).all()


def test_sample_broadcasts_and_converts_to_g() -> None:
    g = parse_grid(make_grid_xml())
    assert g.sample_g("PGA", np.array([[14.0, 14.03]]), 38.98).tolist() == [[0.2, 0.23]]
    assert np.isnan(g.sample_g("PGA", [20.0], [39.0])).all()
    assert parse_grid(make_grid_xml(pga_units="g")).sample_g("PGA", [14.01], [39.0])[0] == 1
    with pytest.raises(GridError, match="percent of g"):
        g.sample_g("PGV", [14.0], [39.0])


def test_sample_refuses_unknown_method_and_column() -> None:
    g = parse_grid(make_grid_xml())
    with pytest.raises(GridError, match="unknown method"):
        g.sample("PGA", [14.0], [39.0], method="cubic")  # type: ignore[arg-type]
    with pytest.raises(GridError, match="no 'PSA10' column"):
        g.sample("PSA10", [14.0], [39.0])
