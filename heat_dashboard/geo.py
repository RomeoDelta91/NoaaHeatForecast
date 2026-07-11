"""Geospatial helpers built on Shapely only (no GDAL/GeoPandas required).

Districts are read from a plain GeoJSON FeatureCollection, fields are
clipped by testing grid-cell centres against the geometry, and district
statistics are computed from the grid-cell centres that fall inside each
district. Small districts without any grid-cell centre fall back to the
nearest grid point and are flagged as estimates.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from shapely import contains_xy
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

#: Kilometres per degree of latitude (and of longitude at the equator).
KM_PER_DEGREE = 111.195

_NAME_KEYS = ("name", "NAME", "district", "DISTRICT", "shapeName", "ADM1_EN", "NAME_1")


@dataclass(frozen=True)
class District:
    name: str
    geometry: BaseGeometry


def _feature_name(properties: dict) -> str:
    for key in _NAME_KEYS:
        value = properties.get(key)
        if value:
            return str(value)
    return "Unknown"


def load_districts(path: str | Path) -> list[District]:
    """Read an EPSG:4326 GeoJSON FeatureCollection into District objects."""
    with open(path, encoding="utf-8") as handle:
        collection = json.load(handle)
    districts = []
    for feature in collection.get("features", []):
        geometry = make_valid(shape(feature["geometry"]))
        if geometry.is_empty:
            continue
        districts.append(District(_feature_name(feature.get("properties", {})), geometry))
    if not districts:
        raise ValueError(f"No district geometries found in {path}")
    return sorted(districts, key=lambda item: item.name)


def country_geometry(districts: list[District]) -> BaseGeometry:
    """Union of every district: the national boundary."""
    return unary_union([district.geometry for district in districts])


def district_by_name(districts: list[District], name: str) -> District | None:
    for district in districts:
        if district.name == name:
            return district
    return None


def _grid_centres(field: xr.DataArray) -> tuple[np.ndarray, np.ndarray]:
    lon2d, lat2d = np.meshgrid(field["lon"].values, field["lat"].values)
    return lon2d, lat2d


def clip_to_geometry(field: xr.DataArray, geometry: BaseGeometry, buffer_degrees: float = 0.05) -> xr.DataArray:
    """Mask grid cells whose centres fall outside the (slightly buffered) geometry."""
    lon2d, lat2d = _grid_centres(field)
    mask = contains_xy(geometry.buffer(buffer_degrees), lon2d, lat2d)
    return field.where(xr.DataArray(mask, dims=("lat", "lon"), coords={"lat": field["lat"], "lon": field["lon"]}))


def geometry_area_km2(geometry: BaseGeometry) -> float:
    """Approximate area of an EPSG:4326 geometry in km²."""
    latitude = geometry.centroid.y
    return float(geometry.area * KM_PER_DEGREE**2 * math.cos(math.radians(latitude)))


def district_statistics(field: xr.DataArray, districts: list[District], probability_cutoff: float) -> pd.DataFrame:
    """Per-district summary of a probability field.

    Returns a DataFrame sorted by descending mean probability with columns:
    District, Mean probability (%), Max probability (%),
    "Area ≥ <cutoff>% (km²)", District area (km²), Nearest-grid estimate.
    """
    lon2d, lat2d = _grid_centres(field)
    values = np.asarray(field.values, dtype=float)
    risk_column = f"Area ≥ {probability_cutoff:.0f}% (km²)"

    rows = []
    for district in districts:
        area_km2 = geometry_area_km2(district.geometry)
        inside = contains_xy(district.geometry, lon2d, lat2d)
        cell_values = values[inside]
        cell_values = cell_values[np.isfinite(cell_values)]
        if cell_values.size:
            estimate = False
            mean_value = float(cell_values.mean())
            max_value = float(cell_values.max())
            at_risk_share = float((cell_values >= probability_cutoff).mean())
        else:
            # District too small to contain a grid-cell centre: use the
            # grid point nearest its representative point.
            estimate = True
            point = district.geometry.representative_point()
            nearest = field.sel(lon=point.x, lat=point.y, method="nearest")
            value = float(nearest.values)
            mean_value = max_value = value if np.isfinite(value) else float("nan")
            at_risk_share = 1.0 if mean_value >= probability_cutoff else 0.0
        rows.append(
            {
                "District": district.name,
                "Mean probability (%)": mean_value,
                "Max probability (%)": max_value,
                risk_column: at_risk_share * area_km2,
                "District area (km²)": area_km2,
                "Nearest-grid estimate": estimate,
            }
        )

    frame = pd.DataFrame(rows)
    return frame.sort_values("Mean probability (%)", ascending=False, ignore_index=True)


def district_tercile_statistics(field: xr.DataArray, districts: list[District]) -> pd.DataFrame:
    """Per-district mean tercile probabilities and the dominant category.

    ``field`` must have (category, lat, lon) dimensions with the category
    labels as coordinates. Districts without a grid-cell centre fall back
    to the nearest grid point and are flagged as estimates.
    """
    categories = [str(item) for item in field["category"].values]
    lon2d, lat2d = _grid_centres(field)
    values = np.asarray(field.values, dtype=float)

    rows = []
    for district in districts:
        inside = contains_xy(district.geometry, lon2d, lat2d)
        estimate = False
        means = []
        for index in range(len(categories)):
            cell_values = values[index][inside]
            cell_values = cell_values[np.isfinite(cell_values)]
            means.append(float(cell_values.mean()) if cell_values.size else float("nan"))
        if not any(np.isfinite(means)):
            estimate = True
            point = district.geometry.representative_point()
            nearest = field.sel(lon=point.x, lat=point.y, method="nearest")
            means = [float(value) for value in np.asarray(nearest.values, dtype=float)]
        dominant = categories[int(np.nanargmax(means))] if any(np.isfinite(means)) else "Unavailable"
        row = {"District": district.name}
        for name, value in zip(categories, means):
            row[f"{name} (%)"] = value
        row["Dominant tercile"] = dominant
        row["Nearest-grid estimate"] = estimate
        rows.append(row)

    return pd.DataFrame(rows)
