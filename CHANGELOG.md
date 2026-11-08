# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed

- Documentation site built with [Zensical](https://zensical.org) instead of
  MkDocs Material; its configuration moved from `mkdocs.yml` to
  `zensical.toml`.

## [0.2.0] - 2026-11-04

### Added

- `ShakeGrid.sample` and `ShakeGrid.sample_g`: values at many positions in one
  NumPy call, `nearest` (the same values as `value_at`, ties to even like
  `round`) or `bilinear`; `NaN` outside the grid. On 100,000 points of a real
  grid: 10 ms against 280 ms for a loop, identical to Limen's parser.
- `IngvClient.info` / `parse_info` → `ShakeMapInfo`: the map's `info.json`
  (version, status, history of runs, GMPE, stations, peaks), a few kB to tell
  whether the 12 MB grid changed.
- `IngvClient.stations` / `parse_stations` → `Station`: the stations of
  `stationlist.json`, PGA in g, with the model's prediction. The string
  `"null"` INGV writes for a missing value is read as `None`.
- `IngvClient.uncertainty`: `uncertainty.xml` as a `ShakeGrid` (`STDPGA` in ln g).
- `IngvClient.product` and `shakemap_product_url`: any file of the map's products.
- `updated_after` on `events` and `event_query` (FDSN `updatedafter`).

## [0.1.0] - 2026-11-04

### Added

- `IngvClient`: INGV FDSN events and ShakeMap grids, async, with an injectable
  `httpx.AsyncClient`, `retries` and a `send` hook. A 204 is no events, a 404 is
  no ShakeMap, any other failure raises `IngvError`.
- `parse_grid` / `ShakeGrid`: every column of a ShakeMap 4 `grid.xml`, values at
  a point (`pga_g` in g, `pgv_cm_s`, `mmi`, `value_at`), arrays, the event and
  the map's status. The row order is checked, not assumed.
- `parse_events` / `Event`, `event_query`, `shakemap_grid_url`: the FDSN side,
  as pure functions.
- Extracted from Limen (`src/limen/integrations/ingv/`). On three real grids
  the PGA matches Limen's parser value for value.
