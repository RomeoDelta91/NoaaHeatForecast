"""Download and decode NOAA/CPC GEFS NetCDF guidance.

Every loader returns latitude/longitude-normalised ``xarray.DataArray``
objects subset to the requested bounds, plus a metadata dictionary with at
least ``valid_start``/``valid_end`` ISO timestamps, the source ``url`` and
``filename``. Any network, HTTP, or decoding problem is raised as
:class:`NOAADataError`; the Streamlit app catches it and falls back to
demo data.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import numpy as np
import requests
import xarray as xr

from .config import (
    CONTEXT_PRODUCTS,
    DOWNLOAD_TIMEOUT,
    HeatProduct,
    context_filename,
    context_url,
    wind_filenames,
    NOAA_BASE_URL,
)


class NOAADataError(Exception):
    """The requested NOAA/CPC product could not be downloaded or decoded."""


def _download(url: str) -> bytes:
    try:
        response = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise NOAADataError(f"Could not download {url}: {exc}") from exc
    if not response.content:
        raise NOAADataError(f"Empty response from {url}")
    return response.content


def _open_dataset(raw: bytes, url: str) -> xr.Dataset:
    """Decode NetCDF bytes with whichever installed engine understands them."""
    handle = tempfile.NamedTemporaryFile(suffix=".nc", delete=False)
    try:
        handle.write(raw)
        handle.close()
        last_error: Exception | None = None
        for engine in ("netcdf4", "h5netcdf", "scipy"):
            try:
                with xr.open_dataset(handle.name, engine=engine) as dataset:
                    return dataset.load()
            except Exception as exc:  # try the next engine
                last_error = exc
        raise NOAADataError(f"Could not decode NetCDF from {url}: {last_error}")
    finally:
        os.unlink(handle.name)


def normalize_coordinates(dataset: xr.Dataset) -> xr.Dataset:
    """Rename latitude/longitude to lat/lon, convert 0–360° longitudes to ±180°, and sort."""
    renames = {}
    for candidate, target in (("latitude", "lat"), ("longitude", "lon"), ("Lat", "lat"), ("Lon", "lon"), ("X", "lon"), ("Y", "lat")):
        if candidate in dataset.dims or candidate in dataset.coords:
            renames[candidate] = target
    if renames:
        dataset = dataset.rename(renames)
    if "lat" not in dataset.coords or "lon" not in dataset.coords:
        raise NOAADataError("Dataset has no recognisable latitude/longitude coordinates.")
    if float(dataset["lon"].max()) > 180.0:
        dataset = dataset.assign_coords(lon=((dataset["lon"] + 180.0) % 360.0) - 180.0)
    return dataset.sortby("lat").sortby("lon")


def _select_field(dataset: xr.Dataset) -> xr.DataArray:
    """Pick the first data variable carrying lat/lon dims and squeeze the rest."""
    for name, variable in dataset.data_vars.items():
        if "lat" in variable.dims and "lon" in variable.dims:
            field = variable
            for dim in [d for d in field.dims if d not in ("lat", "lon")]:
                field = field.isel({dim: 0})
            return field.squeeze(drop=True)
    raise NOAADataError("Dataset contains no gridded variable with lat/lon dimensions.")


def _subset(field: xr.DataArray, bounds: tuple[float, float, float, float]) -> xr.DataArray:
    west, east, south, north = bounds
    subset = field.sel(lon=slice(west, east), lat=slice(south, north))
    if subset.sizes.get("lat", 0) == 0 or subset.sizes.get("lon", 0) == 0:
        raise NOAADataError("The NOAA grid does not overlap the requested bounds.")
    return subset


def _valid_period(week: int) -> tuple[str, str]:
    """Nominal validity window: week 1 = days 1–7, week 2 = days 8–14."""
    issuance = date.today()
    start = issuance + timedelta(days=1 if week == 1 else 8)
    end = issuance + timedelta(days=7 if week == 1 else 14)
    return start.isoformat(), end.isoformat()


def _load_gridded(url: str, bounds: tuple[float, float, float, float]) -> tuple[xr.DataArray, bytes]:
    raw = _download(url)
    dataset = normalize_coordinates(_open_dataset(raw, url))
    return _subset(_select_field(dataset), bounds), raw


def load_heat_probability(
    product: HeatProduct,
    week: int,
    threshold: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, dict, bytes]:
    """Load one excessive-heat probability grid (percent, 0–100)."""
    url = product.url(week, threshold)
    field, raw = _load_gridded(url, bounds)
    values = np.asarray(field.values, dtype=float)
    if np.isfinite(values).any() and np.nanmax(values) <= 1.5:
        field = field * 100.0  # fractional probabilities → percent
    field = field.clip(0, 100)
    field.attrs["units"] = "%"
    valid_start, valid_end = _valid_period(week)
    metadata = {
        "source": "NOAA/CPC GEFS",
        "product": product.label,
        "variable": product.prefix,
        "week": week,
        "threshold": threshold,
        "threshold_type": "percentile" if threshold >= 50 else "fixed_celsius",
        "url": url,
        "filename": product.filename(week, threshold),
        "valid_start": valid_start,
        "valid_end": valid_end,
    }
    return field, metadata, raw


def load_percentile_climatology(
    product: HeatProduct,
    week: int,
    percentile: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, dict, bytes]:
    """Load the local temperature (°C) matching a climatological percentile."""
    url = product.climatology_url(week, percentile)
    field, raw = _load_gridded(url, bounds)
    if np.isfinite(field.values).any() and float(np.nanmax(field.values)) > 150.0:
        field = field - 273.15  # Kelvin → Celsius
    field.attrs["units"] = "°C"
    valid_start, valid_end = _valid_period(week)
    metadata = {
        "source": "NOAA/CPC GEFS climatology",
        "product": product.label,
        "variable": product.prefix,
        "week": week,
        "percentile": percentile,
        "url": url,
        "filename": product.climatology_filename(week, percentile),
        "valid_start": valid_start,
        "valid_end": valid_end,
    }
    return field, metadata, raw


def load_context_field(
    product_name: str,
    view: str,
    week: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, dict]:
    """Load one scalar context field (MSLP, Z500, or 2-m temperature)."""
    product = CONTEXT_PRODUCTS[product_name]
    if view in product.views:
        filename = context_filename(product.variable, view, week)
        url = context_url(filename)
        field, _ = _load_gridded(url, bounds)
        urls = [url]
    else:
        # Reconstruct the missing view: climatology = average − anomaly.
        average_url = context_url(context_filename(product.variable, "Average", week))
        anomaly_url = context_url(context_filename(product.variable, "Anomaly", week))
        average, _ = _load_gridded(average_url, bounds)
        anomaly, _ = _load_gridded(anomaly_url, bounds)
        field = average - anomaly
        filename = "derived"
        urls = [average_url, anomaly_url]
    if product.variable == "t2m" and np.isfinite(field.values).any() and float(np.nanmax(field.values)) > 150.0 and view != "Anomaly":
        field = field - 273.15
    if product.variable == "mslp" and np.isfinite(field.values).any() and float(np.nanmax(field.values)) > 20000.0 and view != "Anomaly":
        field = field / 100.0  # Pa → hPa
    field.attrs["units"] = product.unit
    field.attrs["view"] = view
    valid_start, valid_end = _valid_period(week)
    metadata = {
        "source": "NOAA/CPC GEFS",
        "product": product_name,
        "view": view,
        "week": week,
        "unit": product.unit,
        "url": urls if len(urls) > 1 else urls[0],
        "filename": filename,
        "valid_start": valid_start,
        "valid_end": valid_end,
    }
    return field, metadata


def load_wind_field(
    level: int,
    view: str,
    week: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray, dict]:
    """Load wind components and speed for one level; returns (speed, u, v, metadata)."""
    u_name, v_name = wind_filenames(level, view, week)
    u_url, v_url = context_url(u_name), context_url(v_name)
    u, _ = _load_gridded(u_url, bounds)
    v, _ = _load_gridded(v_url, bounds)
    u, v = xr.align(u, v, join="inner")
    speed = np.hypot(u, v)
    speed.attrs["units"] = "m/s"
    speed.attrs["view"] = view
    valid_start, valid_end = _valid_period(week)
    metadata = {
        "source": "NOAA/CPC GEFS",
        "product": f"{'10-m' if level == 10 else f'{level}-hPa'} wind",
        "view": view,
        "week": week,
        "unit": "m/s",
        "url": [u_url, v_url],
        "filename": [u_name, v_name],
        "valid_start": valid_start,
        "valid_end": valid_end,
    }
    return speed, u, v, metadata


def dataarray_to_netcdf_bytes(field: xr.DataArray, name: str) -> bytes:
    """Serialise a DataArray to NetCDF bytes for a Streamlit download button."""
    clean = field.astype("float32")
    clean.name = name
    clean.attrs = {key: str(value) for key, value in field.attrs.items()}
    dataset = clean.to_dataset()
    dataset.attrs["source"] = f"Suriname Heat Forecast Dashboard ({NOAA_BASE_URL})"
    return bytes(dataset.to_netcdf())
