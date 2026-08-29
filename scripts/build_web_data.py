"""Generate the static JSON dataset consumed by the React dashboard.

The browser cannot download NOAA's NetCDF files itself: the CPC server
sends no CORS headers, and NetCDF4 is HDF5 underneath. So this script
runs the existing ``heat_dashboard`` pipeline server-side (locally or in
CI) and writes small JSON files that the static site fetches on demand.

Each field is written as its own file so the site loads only what the
visitor selects. Districts are baked into a per-grid index, which lets
the browser recompute district statistics for any risk cutoff without
another download.

Usage:
    python scripts/build_web_data.py [--out web/public/data] [--demo]
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr
from shapely import contains_xy

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from heat_dashboard.config import (  # noqa: E402
    BOUNDARY_FILE,
    CONTEXT_PRODUCTS,
    HEAT_PRODUCTS,
    PERCENTILE_THRESHOLDS,
    STATIONS,
    SURINAME_BOUNDS,
    WIND_LEVELS,
)
from heat_dashboard.demo import demo_context, demo_probability, demo_wind  # noqa: E402
from heat_dashboard.geo import (  # noqa: E402
    KM_PER_DEGREE,
    country_geometry,
    geometry_area_km2,
    load_districts,
)
from heat_dashboard.noaa import (  # noqa: E402
    NOAADataError,
    load_context_field,
    load_heat_probability,
    load_percentile_climatology,
    load_wind_field,
)

#: Regional context is generated once at this buffer; the site crops it.
CONTEXT_BUFFER_DEGREES = 12.0

#: Cell budgets keep each JSON file small enough for a static host.
MAX_CONTEXT_CELLS = 120
MAX_WIND_CELLS = 80

VIEWS = ("Average", "Anomaly", "Climatology")


def rounded(values: np.ndarray, digits: int) -> list:
    """Flatten to a JSON list, turning non-finite values into null."""
    flat = np.asarray(values, dtype=float).ravel()
    return [None if not math.isfinite(v) else round(float(v), digits) for v in flat]


def coarsen(field: xr.DataArray, max_cells: int) -> xr.DataArray:
    """Subsample a field so neither dimension exceeds ``max_cells``."""
    step_lat = max(1, math.ceil(field.sizes["lat"] / max_cells))
    step_lon = max(1, math.ceil(field.sizes["lon"] / max_cells))
    if step_lat == 1 and step_lon == 1:
        return field
    return field.isel(lat=slice(None, None, step_lat), lon=slice(None, None, step_lon))


def grid_signature(field: xr.DataArray) -> str:
    lat = np.asarray(field["lat"].values, dtype=float)
    lon = np.asarray(field["lon"].values, dtype=float)
    return f"{lat.size}x{lon.size}_{lat[0]:.4f}_{lat[-1]:.4f}_{lon[0]:.4f}_{lon[-1]:.4f}"


class GridRegistry:
    """Assigns ids to unique grids and bakes district membership into them."""

    def __init__(self, districts, country):
        self.districts = districts
        self.country = country
        self._ids: dict[str, str] = {}
        self.payloads: dict[str, dict] = {}

    def register(self, field: xr.DataArray) -> str:
        signature = grid_signature(field)
        if signature in self._ids:
            return self._ids[signature]

        grid_id = f"g{len(self._ids) + 1}"
        self._ids[signature] = grid_id

        lat = np.asarray(field["lat"].values, dtype=float)
        lon = np.asarray(field["lon"].values, dtype=float)
        lon2d, lat2d = np.meshgrid(lon, lat)

        # -1 marks a cell centre outside every district.
        district_index = np.full(lon2d.shape, -1, dtype=int)
        for position, district in enumerate(self.districts):
            inside = contains_xy(district.geometry, lon2d, lat2d)
            district_index[inside] = position

        in_country = contains_xy(self.country.buffer(0.05), lon2d, lat2d)

        # Cell area shrinks with latitude; used for the area-at-risk metric.
        step_lat = float(abs(lat[1] - lat[0])) if lat.size > 1 else 1.0
        step_lon = float(abs(lon[1] - lon[0])) if lon.size > 1 else 1.0
        cell_area = (
            step_lat * KM_PER_DEGREE * step_lon * KM_PER_DEGREE * np.cos(np.radians(lat2d))
        )

        self.payloads[grid_id] = {
            "id": grid_id,
            "lat": [round(float(v), 4) for v in lat],
            "lon": [round(float(v), 4) for v in lon],
            "districtIndex": [int(v) for v in district_index.ravel()],
            "inCountry": [bool(v) for v in in_country.ravel()],
            "cellAreaKm2": rounded(cell_area, 1),
        }
        return grid_id


def field_payload(field: xr.DataArray, grid_id: str, metadata: dict, digits: int = 1) -> dict:
    return {
        "gridId": grid_id,
        "values": rounded(field.values, digits),
        "meta": json_safe(metadata),
    }


def json_safe(value):
    """Make metadata JSON-serialisable (numpy scalars, Paths, tuples)."""
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Path, payload: dict) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    path.write_text(text, encoding="utf-8")
    return len(text.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="web/public/data", help="Output directory")
    parser.add_argument("--demo", action="store_true", help="Skip NOAA and generate demo data only")
    arguments = parser.parse_args()

    out_dir = (PROJECT_ROOT / arguments.out).resolve()
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    districts = load_districts(BOUNDARY_FILE)
    country = country_geometry(districts)
    registry = GridRegistry(districts, country)

    manifest = {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bounds": list(SURINAME_BOUNDS),
        "contextBuffer": CONTEXT_BUFFER_DEGREES,
        # Areas, bounds and representative points come from the official
        # geometry so the browser can reproduce the Streamlit statistics
        # (including the nearest-grid fallback for small districts).
        "districts": [
            {
                "name": district.name,
                "areaKm2": round(geometry_area_km2(district.geometry), 1),
                "bounds": [round(v, 4) for v in district.geometry.bounds],
                "point": [
                    round(district.geometry.representative_point().x, 4),
                    round(district.geometry.representative_point().y, 4),
                ],
            }
            for district in districts
        ],
        "stations": [{"name": n, "lon": lo, "lat": la} for n, lo, la in STATIONS],
        "percentiles": list(PERCENTILE_THRESHOLDS),
        "windLevels": list(WIND_LEVELS),
        "views": list(VIEWS),
        "heatProducts": [],
        "contextProducts": [],
        "fields": {},
        "liveCount": 0,
        "demoCount": 0,
    }

    total_bytes = 0

    def record(key: str, path: Path, size: int, live: bool) -> None:
        nonlocal total_bytes
        total_bytes += size
        manifest["fields"][key] = {"path": path.relative_to(out_dir).as_posix(), "live": live}
        manifest["liveCount" if live else "demoCount"] += 1

    # ---------------------------------------------------------------- heat
    for product_name, product in HEAT_PRODUCTS.items():
        thresholds = list(product.fixed_thresholds) + list(PERCENTILE_THRESHOLDS)
        manifest["heatProducts"].append(
            {
                "name": product_name,
                "prefix": product.prefix,
                "label": product.label,
                "description": product.description,
                "fixedThresholds": list(product.fixed_thresholds),
                "supportsClimatology": product.prefix in {"tmax", "tmin"},
            }
        )
        for week in (1, 2):
            for threshold in thresholds:
                live = False
                try:
                    if arguments.demo:
                        raise NOAADataError("demo mode requested")
                    field, metadata, _ = load_heat_probability(product, week, threshold, SURINAME_BOUNDS)
                    live = True
                except NOAADataError as exc:
                    field, metadata = demo_probability(week, product_name, threshold)
                    metadata["fallback_reason"] = str(exc)[:400]
                key = f"heat/{product.prefix}/{week}/{threshold}"
                path = out_dir / "heat" / product.prefix / f"wk{week}_{threshold}.json"
                grid_id = registry.register(field)
                size = write_json(path, field_payload(field, grid_id, metadata))
                record(key, path, size, live)
                print(f"  {'live' if live else 'demo'}  {key}")

        # Percentile climatology thresholds for Tmax/Tmin.
        if product.prefix in {"tmax", "tmin"}:
            for week in (1, 2):
                for percentile in PERCENTILE_THRESHOLDS:
                    live = False
                    try:
                        if arguments.demo:
                            raise NOAADataError("demo mode requested")
                        field, metadata, _ = load_percentile_climatology(
                            product, week, percentile, SURINAME_BOUNDS
                        )
                        live = True
                    except NOAADataError as exc:
                        # No demo equivalent exists; skip rather than invent one.
                        print(f"  skip  climatology {product.prefix} wk{week} P{percentile}: {exc}"[:120])
                        continue
                    key = f"climatology/{product.prefix}/{week}/{percentile}"
                    path = out_dir / "climatology" / product.prefix / f"wk{week}_p{percentile}.json"
                    grid_id = registry.register(field)
                    size = write_json(path, field_payload(field, grid_id, metadata))
                    record(key, path, size, live)

    # ------------------------------------------------------------- context
    west, east, south, north = SURINAME_BOUNDS
    context_bounds = (
        west - CONTEXT_BUFFER_DEGREES,
        east + CONTEXT_BUFFER_DEGREES,
        max(-89.0, south - CONTEXT_BUFFER_DEGREES),
        min(89.0, north + CONTEXT_BUFFER_DEGREES),
    )

    for product_name, product in CONTEXT_PRODUCTS.items():
        manifest["contextProducts"].append(
            {"name": product_name, "variable": product.variable, "unit": product.unit}
        )
        for week in (1, 2):
            for view in VIEWS:
                live = False
                try:
                    if arguments.demo:
                        raise NOAADataError("demo mode requested")
                    field, metadata = load_context_field(product_name, view, week, context_bounds)
                    live = True
                except NOAADataError as exc:
                    field, metadata = demo_context(product_name, view, context_bounds)
                    metadata["fallback_reason"] = str(exc)[:400]
                field = coarsen(field, MAX_CONTEXT_CELLS)
                key = f"context/{product.variable}/{week}/{view}"
                path = out_dir / "context" / product.variable / f"wk{week}_{view.lower()}.json"
                grid_id = registry.register(field)
                payload = field_payload(field, grid_id, metadata)
                payload["unit"] = metadata.get("unit", product.unit)
                payload["view"] = view
                size = write_json(path, payload)
                record(key, path, size, live)
                print(f"  {'live' if live else 'demo'}  {key}")

    # ---------------------------------------------------------------- wind
    for level in WIND_LEVELS:
        for week in (1, 2):
            for view in VIEWS:
                live = False
                try:
                    if arguments.demo:
                        raise NOAADataError("demo mode requested")
                    speed, u, v, metadata = load_wind_field(level, view, week, context_bounds)
                    live = True
                except NOAADataError as exc:
                    speed, u, v, metadata = demo_wind(view, context_bounds)
                    metadata["fallback_reason"] = str(exc)[:400]
                speed = coarsen(speed, MAX_WIND_CELLS)
                u = coarsen(u, MAX_WIND_CELLS)
                v = coarsen(v, MAX_WIND_CELLS)
                key = f"wind/{level}/{week}/{view}"
                path = out_dir / "wind" / str(level) / f"wk{week}_{view.lower()}.json"
                grid_id = registry.register(speed)
                payload = field_payload(speed, grid_id, metadata)
                payload["u"] = rounded(u.values, 2)
                payload["v"] = rounded(v.values, 2)
                payload["unit"] = "m/s"
                payload["view"] = view
                size = write_json(path, payload)
                record(key, path, size, live)
                print(f"  {'live' if live else 'demo'}  {key}")

    # ------------------------------------------------------------ supporting
    for grid_id, payload in registry.payloads.items():
        total_bytes += write_json(out_dir / "grids" / f"{grid_id}.json", payload)

    boundaries = json.loads(Path(BOUNDARY_FILE).read_text(encoding="utf-8"))
    total_bytes += write_json(out_dir / "districts.geojson", boundaries)

    manifest["gridIds"] = list(registry.payloads)
    total_bytes += write_json(out_dir / "index.json", manifest)

    print(
        f"\nWrote {len(manifest['fields'])} fields "
        f"({manifest['liveCount']} live, {manifest['demoCount']} demo) "
        f"and {len(registry.payloads)} grids to {out_dir} "
        f"({total_bytes / 1_048_576:.1f} MB uncompressed)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
