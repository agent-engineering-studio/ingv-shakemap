from __future__ import annotations

from datetime import UTC, datetime

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
