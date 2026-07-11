"""Matplotlib map builders for the dashboard.

All functions return an open ``matplotlib`` figure; the caller is
responsible for closing it (the Streamlit app does so after rendering).
"""

from __future__ import annotations

import io
import math

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import xarray as xr
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from .config import STATIONS
from .geo import District, country_geometry

BOUNDARY_COLOR = "#374151"
SELECTED_COLOR = "#1d4ed8"


def _polygons(geometry: BaseGeometry):
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, MultiPolygon):
        yield from geometry.geoms
    elif hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _polygons(part)


def _draw_geometry(ax, geometry: BaseGeometry, color: str, linewidth: float, zorder: int = 5) -> None:
    for polygon in _polygons(geometry):
        x, y = polygon.exterior.xy
        ax.plot(x, y, color=color, linewidth=linewidth, zorder=zorder)


def _draw_districts(
    ax,
    districts: list[District],
    selected_district: str | None = None,
    show_boundaries: bool = True,
    show_labels: bool = False,
) -> None:
    for district in districts:
        selected = district.name == selected_district
        if show_boundaries or selected:
            _draw_geometry(
                ax,
                district.geometry,
                SELECTED_COLOR if selected else BOUNDARY_COLOR,
                1.6 if selected else 0.7,
                zorder=6 if selected else 5,
            )
        if show_labels:
            point = district.geometry.representative_point()
            ax.annotate(
                district.name,
                (point.x, point.y),
                ha="center",
                va="center",
                fontsize=7,
                color="#111827",
                zorder=7,
                path_effects=None,
            )


def _draw_stations(ax) -> None:
    for name, lon, lat in STATIONS:
        ax.plot(lon, lat, marker="^", markersize=5, color="#0f172a", markerfacecolor="#fbbf24", zorder=8)
        ax.annotate(name, (lon, lat), xytext=(3, 3), textcoords="offset points", fontsize=6, color="#334155", zorder=8)


def _base_axes(title: str, extent: tuple[float, float, float, float]):
    fig, ax = plt.subplots(figsize=(8.6, 8.2))
    west, east, south, north = extent
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    mid_lat = (south + north) / 2.0
    ax.set_aspect(1.0 / max(math.cos(math.radians(mid_lat)), 0.2))
    ax.set_title(title, fontsize=11, fontweight="bold", loc="left")
    ax.set_xlabel("Longitude (°E)", fontsize=8)
    ax.set_ylabel("Latitude (°N)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(color="#e5e7eb", linewidth=0.5, alpha=0.7, zorder=0)
    ax.set_facecolor("#f8fafc")
    return fig, ax


def _mesh(ax, field: xr.DataArray, cmap: str, vmin: float | None, vmax: float | None):
    return ax.pcolormesh(
        field["lon"].values,
        field["lat"].values,
        np.asarray(field.values, dtype=float),
        cmap=cmap,
        vmin=vmin,
        vmax=vmax,
        shading="auto",
        zorder=2,
    )


def probability_map(
    field: xr.DataArray,
    districts: list[District],
    title: str,
    extent: tuple[float, float, float, float],
    selected_district: str | None = None,
    show_boundaries: bool = True,
    show_labels: bool = True,
    show_stations: bool = True,
):
    """Excessive-heat probability map (0–100 %)."""
    fig, ax = _base_axes(title, extent)
    mesh = _mesh(ax, field, "YlOrRd", 0, 100)
    fig.colorbar(mesh, ax=ax, shrink=0.75, pad=0.02, label="Probability (%)")
    _draw_geometry(ax, country_geometry(districts), "#111827", 1.1, zorder=6)
    _draw_districts(ax, districts, selected_district, show_boundaries, show_labels)
    if show_stations:
        _draw_stations(ax)
    fig.tight_layout()
    return fig


def threshold_map(
    field: xr.DataArray,
    districts: list[District],
    title: str,
    extent: tuple[float, float, float, float],
):
    """Climatological percentile-temperature threshold map (°C)."""
    fig, ax = _base_axes(title, extent)
    mesh = _mesh(ax, field, "inferno", None, None)
    fig.colorbar(mesh, ax=ax, shrink=0.75, pad=0.02, label="Temperature (°C)")
    _draw_geometry(ax, country_geometry(districts), "#f8fafc", 1.1, zorder=6)
    _draw_districts(ax, districts, show_boundaries=True, show_labels=False)
    fig.tight_layout()
    return fig


def context_map(
    field: xr.DataArray,
    districts: list[District],
    title: str,
    extent: tuple[float, float, float, float],
    unit: str,
    u: xr.DataArray | None = None,
    v: xr.DataArray | None = None,
):
    """Regional context map, optionally with wind vectors."""
    fig, ax = _base_axes(title, extent)
    values = np.asarray(field.values, dtype=float)
    is_anomaly = field.attrs.get("view") == "Anomaly"
    if is_anomaly and np.isfinite(values).any():
        limit = float(np.nanmax(np.abs(values))) or 1.0
        mesh = _mesh(ax, field, "RdBu_r", -limit, limit)
    else:
        mesh = _mesh(ax, field, "viridis", None, None)
    fig.colorbar(mesh, ax=ax, shrink=0.75, pad=0.02, label=unit)

    if u is not None and v is not None:
        step = max(1, u.sizes["lon"] // 22, u.sizes["lat"] // 22)
        lon = u["lon"].values[::step]
        lat = u["lat"].values[::step]
        ax.quiver(
            lon,
            lat,
            np.asarray(u.values, dtype=float)[::step, ::step],
            np.asarray(v.values, dtype=float)[::step, ::step],
            color="#111827",
            width=0.0022,
            scale_units="xy",
            zorder=4,
        )

    _draw_geometry(ax, country_geometry(districts), "#111827", 1.2, zorder=6)
    fig.tight_layout()
    return fig


def figure_png_bytes(fig) -> bytes:
    """Render a figure to PNG bytes for a Streamlit download button."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=160, bbox_inches="tight", facecolor="white")
    return buffer.getvalue()
