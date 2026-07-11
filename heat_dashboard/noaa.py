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
import re
import tempfile
from datetime import date, timedelta
from functools import lru_cache

import numpy as np
import requests
import xarray as xr

from .config import (
    CONTEXT_LISTING_DIRECTORIES,
    CONTEXT_PRODUCTS,
    DOWNLOAD_TIMEOUT,
    HEAT_LISTING_DIRECTORIES,
    HeatProduct,
    SUBSEASONAL_DATA_URL,
    SUBSEASONAL_PERIODS,
    TERCILE_CATEGORIES,
    context_filename,
    context_url,
    tercile_url,
    wind_filenames,
    wind_level_tag,
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


def parse_listing(html: str) -> tuple[str, ...]:
    """Extract the ``.nc`` filenames from an Apache-style index page."""
    names = re.findall(r'href="([^"?/]+\.nc)"', html, flags=re.IGNORECASE)
    return tuple(sorted(set(names)))


@lru_cache(maxsize=64)
def _directory_files(directory: str) -> tuple[str, ...]:
    """List the NetCDF files in a NOAA directory; empty when unreachable."""
    try:
        response = requests.get(directory, timeout=DOWNLOAD_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException:
        return ()
    return parse_listing(response.text)


def filename_matches(name: str, token_groups: list[tuple[str, ...]], exclude: tuple[str, ...] = ()) -> bool:
    """True when the name has one token from every group and none excluded."""
    low = name.lower()
    if any(token in low for token in exclude):
        return False
    return all(any(token in low for token in group) for group in token_groups)


def _week_tokens(week: int) -> tuple[str, ...]:
    return (f"wk{week}", f"week{week}", f"week-{week}", f"_w{week}", f"day{'1-7' if week == 1 else '8-14'}")


def _discover_url(
    directories: tuple[str, ...],
    token_groups: list[tuple[str, ...]],
    exclude: tuple[str, ...] = (),
) -> str | None:
    """Search directory listings for the newest file matching the tokens."""
    for directory in directories:
        matches = [name for name in _directory_files(directory) if filename_matches(name, token_groups, exclude)]
        if matches:
            return directory + sorted(matches)[-1]
    return None


def _resolve_and_download(
    candidates: list[str],
    directories: tuple[str, ...],
    token_groups: list[tuple[str, ...]],
    exclude: tuple[str, ...],
    description: str,
) -> tuple[str, bytes]:
    """Try exact URL guesses, then fall back to listing discovery."""
    tried = []
    for url in candidates:
        try:
            return url, _download(url)
        except NOAADataError:
            tried.append(url)
    discovered = _discover_url(directories, token_groups, exclude)
    if discovered and discovered not in tried:
        try:
            return discovered, _download(discovered)
        except NOAADataError:
            tried.append(discovered)
    raise NOAADataError(
        f"No NOAA file found for {description}. "
        f"Tried: {', '.join(tried) or 'none'}. "
        f"Searched listings: {', '.join(directories)}."
    )


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


def _decode(raw: bytes, url: str, bounds: tuple[float, float, float, float]) -> xr.DataArray:
    dataset = normalize_coordinates(_open_dataset(raw, url))
    return _subset(_select_field(dataset), bounds)


def load_heat_probability(
    product: HeatProduct,
    week: int,
    threshold: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, dict, bytes]:
    """Load one excessive-heat probability grid (percent, 0–100)."""
    if threshold >= 50:
        threshold_tokens = (f"{product.prefix}{threshold}", f"p{threshold}", f"{threshold}th")
        exclude = ("climo", "clim", "thresh", "anom")
    else:
        threshold_tokens = (f"{product.prefix}{threshold}", f"ge{threshold}", f"{threshold}c")
        exclude = ("climo", "clim", "anom")
    url, raw = _resolve_and_download(
        product.url_candidates(week, threshold),
        HEAT_LISTING_DIRECTORIES,
        [(product.prefix,), _week_tokens(week), threshold_tokens],
        exclude,
        f"{product.label} week {week} threshold {threshold}",
    )
    field = _decode(raw, url, bounds)
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
        "filename": url.rsplit("/", 1)[-1],
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
    url, raw = _resolve_and_download(
        product.climatology_url_candidates(week, percentile),
        HEAT_LISTING_DIRECTORIES,
        [(product.prefix,), _week_tokens(week), (f"climo{percentile}", f"p{percentile}", str(percentile)), ("climo", "clim", "thresh")],
        (),
        f"{product.label} week {week} P{percentile} climatology",
    )
    field = _decode(raw, url, bounds)
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
        "filename": url.rsplit("/", 1)[-1],
        "valid_start": valid_start,
        "valid_end": valid_end,
    }
    return field, metadata, raw


_CONTEXT_VARIABLE_TOKENS = {
    "mslp": ("mslp", "slp", "prmsl", "psl"),
    "hgt500": ("hgt500", "z500", "500hgt", "gph500"),
    "t2m": ("t2m", "tmp2m", "2mt", "temp2m"),
}


def _view_tokens(base: str, view: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(required, excluded) tokens telling weekly-mean files from anomalies.

    NOAA appends ``t`` (total/mean) or ``a`` (anomaly) to the variable name:
    ``wk1_mslpt.nc`` vs ``wk1_mslpa.nc``.
    """
    if view == "Anomaly":
        return ((f"{base}a", f"{base}_a", "anom"), ("climo", "clim"))
    return ((f"{base}t", f"{base}_t", "avg", "mean"), (f"{base}a.", f"{base}_a", "anom", "climo", "clim"))


def _load_context_view(variable: str, view: str, week: int, bounds) -> tuple[xr.DataArray, str]:
    required, excluded = _view_tokens(variable, view)
    url, raw = _resolve_and_download(
        [context_url(context_filename(variable, view, week))],
        CONTEXT_LISTING_DIRECTORIES,
        [_CONTEXT_VARIABLE_TOKENS.get(variable, (variable,)), _week_tokens(week), required],
        excluded,
        f"{variable} {view} week {week}",
    )
    return _decode(raw, url, bounds), url


def load_context_field(
    product_name: str,
    view: str,
    week: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, dict]:
    """Load one scalar context field (MSLP, Z500, or 2-m temperature)."""
    product = CONTEXT_PRODUCTS[product_name]
    if view in product.views:
        field, url = _load_context_view(product.variable, view, week, bounds)
        filename = url.rsplit("/", 1)[-1]
        urls = [url]
    else:
        # Reconstruct the missing view: climatology = average − anomaly.
        average, average_url = _load_context_view(product.variable, "Average", week, bounds)
        anomaly, anomaly_url = _load_context_view(product.variable, "Anomaly", week, bounds)
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


def _load_wind_component(component: str, level: int, view: str, week: int, bounds) -> tuple[xr.DataArray, str]:
    tag = wind_level_tag(level)
    base = f"{component}{tag}"
    required, excluded = _view_tokens(base, view)
    u_name, v_name = wind_filenames(level, view, week)
    url, raw = _resolve_and_download(
        [context_url(u_name if component == "u" else v_name)],
        CONTEXT_LISTING_DIRECTORIES,
        [(base, f"{component}wnd{tag}", f"{component}grd{tag}"), _week_tokens(week), required],
        excluded,
        f"{component}-wind {level} {view} week {week}",
    )
    return _decode(raw, url, bounds), url


def load_wind_field(
    level: int,
    view: str,
    week: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray, dict]:
    """Load wind components and speed for one level; returns (speed, u, v, metadata).

    The published views are the weekly mean (``wk1_u850t.nc``) and the
    anomaly (``wk1_u850a.nc``); climatology is derived as mean − anomaly.
    """
    if view == "Climatology":
        u_mean, u_mean_url = _load_wind_component("u", level, "Average", week, bounds)
        u_anom, u_anom_url = _load_wind_component("u", level, "Anomaly", week, bounds)
        v_mean, v_mean_url = _load_wind_component("v", level, "Average", week, bounds)
        v_anom, v_anom_url = _load_wind_component("v", level, "Anomaly", week, bounds)
        u_mean, u_anom = xr.align(u_mean, u_anom, join="inner")
        v_mean, v_anom = xr.align(v_mean, v_anom, join="inner")
        u = u_mean - u_anom
        v = v_mean - v_anom
        urls = [u_mean_url, u_anom_url, v_mean_url, v_anom_url]
    else:
        u, u_url = _load_wind_component("u", level, view, week, bounds)
        v, v_url = _load_wind_component("v", level, view, week, bounds)
        urls = [u_url, v_url]
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
        "url": urls,
        "filename": [item.rsplit("/", 1)[-1] for item in urls],
        "valid_start": valid_start,
        "valid_end": valid_end,
    }
    return speed, u, v, metadata


def _select_tercile_field(dataset: xr.Dataset) -> xr.DataArray:
    """Pick the tercile variable and keep its 3-category dimension.

    The reference tool reads variable ``precip`` whose non-spatial
    dimension of size 3 holds the below/near/above-normal probabilities
    (in that order); any other extra dimension (e.g. time) is reduced to
    its first element.
    """
    if "precip" in dataset.data_vars:
        field = dataset["precip"]
    else:
        field = _select_field_with_categories(dataset)
    category_dim = None
    for dim in field.dims:
        if dim in ("lat", "lon"):
            continue
        if field.sizes[dim] == 3 and category_dim is None:
            category_dim = dim
        else:
            field = field.isel({dim: 0})
    if category_dim is None:
        raise NOAADataError("Tercile dataset has no 3-category probability dimension.")
    field = field.rename({category_dim: "category"})
    field = field.assign_coords(category=list(TERCILE_CATEGORIES))
    return field.transpose("category", "lat", "lon")


def _select_field_with_categories(dataset: xr.Dataset) -> xr.DataArray:
    for variable in dataset.data_vars.values():
        if "lat" in variable.dims and "lon" in variable.dims:
            return variable
    raise NOAADataError("Dataset contains no gridded variable with lat/lon dimensions.")


def load_precip_terciles(
    period: str,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.DataArray, dict, bytes]:
    """Load raw GEFS precipitation tercile probabilities (percent, 0-100).

    Returns a (category, lat, lon) DataArray with the below-, near- and
    above-normal probabilities for the requested period label.
    """
    token, start_day, end_day = SUBSEASONAL_PERIODS[period]
    url, raw = _resolve_and_download(
        [tercile_url(token)],
        (SUBSEASONAL_DATA_URL,),
        [("tercile",), (f"week{token}",)],
        ("hind", "fcst", "chirps"),
        f"GEFS precipitation terciles {period}",
    )
    dataset = normalize_coordinates(_open_dataset(raw, url))
    field = _subset(_select_tercile_field(dataset), bounds)
    values = np.asarray(field.values, dtype=float)
    if np.isfinite(values).any() and np.nanmax(values) <= 1.5:
        field = field * 100.0  # fractional probabilities -> percent
    field = field.clip(0, 100)
    field.attrs["units"] = "%"
    issuance = date.today()
    metadata = {
        "source": "NOAA/CPC GEFS subseasonal",
        "product": "Precipitation tercile probabilities",
        "period": period,
        "categories": list(TERCILE_CATEGORIES),
        "url": url,
        "filename": url.rsplit("/", 1)[-1],
        "valid_start": (issuance + timedelta(days=start_day)).isoformat(),
        "valid_end": (issuance + timedelta(days=end_day)).isoformat(),
    }
    return field, metadata, raw


def dataarray_to_netcdf_bytes(field: xr.DataArray, name: str) -> bytes:
    """Serialise a DataArray to NetCDF bytes for a Streamlit download button."""
    clean = field.astype("float32")
    clean.name = name
    clean.attrs = {key: str(value) for key, value in field.attrs.items()}
    dataset = clean.to_dataset()
    dataset.attrs["source"] = f"Suriname Heat Forecast Dashboard ({NOAA_BASE_URL})"
    return bytes(dataset.to_netcdf())
