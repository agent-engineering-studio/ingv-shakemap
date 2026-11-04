# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
