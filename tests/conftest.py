from __future__ import annotations


def make_grid_xml(
    *,
    nlon: int = 4,
    nlat: int = 3,
    lon_min: float = 14.0,
    lat_max: float = 39.0,
    step: float = 0.01,
    pga_units: str = "%g",
    order: str = "north-west",
    rows_override: int | None = None,
    with_event: bool = True,
) -> bytes:
    """A small ShakeMap grid: PGA = 10*row + col (in pga_units), MMI = row + 2, PGV = col."""
    lat_min = lat_max - (nlat - 1) * step
    lon_max = lon_min + (nlon - 1) * step
    lines = []
    lats = range(nlat) if order != "south-first" else reversed(range(nlat))
    for r in lats:
        for c in range(nlon):
            lines.append(
                f"{lon_min + c * step:.4f} {lat_max - r * step:.4f} {r + 2} {10 * r + c} {c}"
            )
    if rows_override is not None:
        lines = lines[:rows_override]
    event = (
        '<event event_id="47606532" magnitude="5.5" depth="8.8" lat="38.7938" lon="14.1717" '
        'event_timestamp="2026-10-23T10:19:15" event_description="Tirreno Meridionale [Mare]" />'
        if with_event
        else ""
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<shakemap_grid xmlns="http://earthquake.usgs.gov/eqcenter/shakemap" '
        'event_id="47606532" shakemap_version="4" process_timestamp="2026-10-25T02:06:34" '
        'map_status="automatic">'
        f"{event}"
        f'<grid_specification lon_min="{lon_min}" lat_min="{lat_min}" lon_max="{lon_max}" '
        f'lat_max="{lat_max}" nlon="{nlon}" nlat="{nlat}"/>'
        '<grid_field index="1" name="LON" units="dd" />'
        '<grid_field index="2" name="LAT" units="dd" />'
        '<grid_field index="3" name="MMI" units="intensity" />'
        f'<grid_field index="4" name="PGA" units="{pga_units}" />'
        '<grid_field index="5" name="PGV" units="cm/s" />'
        "<grid_data>\n" + "\n".join(lines) + "\n</grid_data></shakemap_grid>"
    ).encode()
