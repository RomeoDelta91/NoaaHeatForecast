"""Deterministic synthetic fields for demo mode and NOAA-outage fallback.

The generators are seeded from their inputs, so the same selection always
produces the same map, and every field is smooth and physically plausible
enough to exercise the full interface (statistics, clipping, downloads).
"""

from __future__ import annotations

import zlib
from datetime import date, timedelta

import numpy as np
import xarray as xr
from scipy.ndimage import gaussian_filter

from .config import SURINAME_BOUNDS

GRID_STEP = 0.2


def _seed(*parts) -> int:
    return zlib.crc32("|".join(str(part) for part in parts).encode())


def _grid(bounds: tuple[float, float, float, float]) -> tuple[np.ndarray, np.ndarray]:
    west, east, south, north = bounds
    lon = np.arange(west, east + GRID_STEP / 2, GRID_STEP)
    lat = np.arange(south, north + GRID_STEP / 2, GRID_STEP)
    return lon, lat


def _smooth_noise(shape: tuple[int, int], seed: int, sigma: float = 3.0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    noise = gaussian_filter(rng.standard_normal(shape), sigma=sigma)
    peak = np.abs(noise).max()
    return noise / peak if peak else noise


def _dataarray(values: np.ndarray, lon: np.ndarray, lat: np.ndarray, units: str, view: str | None = None) -> xr.DataArray:
    field = xr.DataArray(values.astype("float32"), coords={"lat": lat, "lon": lon}, dims=("lat", "lon"))
    field.attrs["units"] = units
    if view:
        field.attrs["view"] = view
    return field


def _valid_period(week: int) -> tuple[str, str]:
    issuance = date.today()
    start = issuance + timedelta(days=1 if week == 1 else 8)
    end = issuance + timedelta(days=7 if week == 1 else 14)
    return start.isoformat(), end.isoformat()


def demo_probability(week: int, product_name: str, threshold: int) -> tuple[xr.DataArray, dict]:
    """Synthetic excessive-heat probability (0–100 %) over Suriname."""
    lon, lat = _grid(SURINAME_BOUNDS)
    lon2d, lat2d = np.meshgrid(lon, lat)

    # Warmer along the populated north coast, cooler over the interior highlands.
    coastal = np.clip((lat2d - 1.5) / 5.0, 0, 1) ** 1.5
    # Higher thresholds are progressively harder to exceed.
    if threshold >= 50:  # percentile threshold
        severity = (threshold - 80) / 20.0
    else:  # fixed °C threshold
        severity = np.clip((threshold - 33) / 12.0, 0, 1)
    base = 15 + 65 * coastal * (1.0 - 0.65 * severity)
    noise = _smooth_noise(lon2d.shape, _seed("prob", week, product_name, threshold)) * 18
    values = np.clip(base + noise + (5 if week == 2 else 0), 0, 100)

    field = _dataarray(values, lon, lat, "%")
    valid_start, valid_end = _valid_period(week)
    metadata = {
        "source": "Demo data generator",
        "product": product_name,
        "week": week,
        "threshold": threshold,
        "valid_start": valid_start,
        "valid_end": valid_end,
        "note": "Synthetic field for interface testing; not a forecast.",
    }
    return field, metadata


def demo_context(product_name: str, view: str, bounds: tuple[float, float, float, float]) -> tuple[xr.DataArray, dict]:
    """Synthetic scalar context field (MSLP, Z500, or 2-m temperature)."""
    lon, lat = _grid(bounds)
    lon2d, lat2d = np.meshgrid(lon, lat)
    noise = _smooth_noise(lon2d.shape, _seed("context", product_name, view), sigma=4.0)

    if "pressure" in product_name.lower():
        unit = "hPa"
        centre, spread = 1012.0, 3.5
    elif "geopotential" in product_name.lower():
        unit = "gpm"
        centre, spread = 5870.0, 35.0
    else:  # 2-m air temperature
        unit = "°C"
        centre, spread = 27.5, 2.5

    if view == "Anomaly":
        values = noise * spread
    else:
        gradient = (lat2d - lat2d.mean()) / max(np.ptp(lat2d), 1e-6)
        values = centre + gradient * spread + noise * spread * 0.6
        if view == "Climatology":
            values = values - noise * spread * 0.3

    field = _dataarray(values, lon, lat, unit, view)
    valid_start, valid_end = _valid_period(1)
    metadata = {
        "source": "Demo data generator",
        "product": product_name,
        "view": view,
        "unit": unit,
        "valid_start": valid_start,
        "valid_end": valid_end,
        "note": "Synthetic field for interface testing; not a forecast.",
    }
    return field, metadata


def demo_precip_terciles(period: str, bounds: tuple[float, float, float, float]) -> tuple[xr.DataArray, dict]:
    """Synthetic precipitation tercile probabilities that sum to 100 %."""
    from .config import SUBSEASONAL_PERIODS, TERCILE_CATEGORIES

    token, start_day, end_day = SUBSEASONAL_PERIODS[period]
    lon, lat = _grid(bounds)
    lon2d, lat2d = np.meshgrid(lon, lat)

    # Wetter signal toward the interior/south, drier toward the coast,
    # with smooth spatial noise; softmax keeps the three terciles valid.
    wet_signal = 0.8 - 1.2 * np.clip((lat2d - 1.5) / 5.0, 0, 1)
    scores = np.stack(
        [
            -wet_signal + _smooth_noise(lon2d.shape, _seed("precip-bn", period)) * 0.9,
            0.15 + _smooth_noise(lon2d.shape, _seed("precip-nn", period)) * 0.5,
            wet_signal + _smooth_noise(lon2d.shape, _seed("precip-an", period)) * 0.9,
        ]
    )
    weights = np.exp(scores)
    probabilities = weights / weights.sum(axis=0) * 100.0

    field = xr.DataArray(
        probabilities.astype("float32"),
        coords={"category": list(TERCILE_CATEGORIES), "lat": lat, "lon": lon},
        dims=("category", "lat", "lon"),
        attrs={"units": "%"},
    )
    issuance = date.today()
    metadata = {
        "source": "Demo data generator",
        "product": "Precipitation tercile probabilities",
        "period": period,
        "categories": list(TERCILE_CATEGORIES),
        "valid_start": (issuance + timedelta(days=start_day)).isoformat(),
        "valid_end": (issuance + timedelta(days=end_day)).isoformat(),
        "note": "Synthetic field for interface testing; not a forecast.",
    }
    return field, metadata


def demo_wind(view: str, bounds: tuple[float, float, float, float]) -> tuple[xr.DataArray, xr.DataArray, xr.DataArray, dict]:
    """Synthetic trade-wind field; returns (speed, u, v, metadata)."""
    lon, lat = _grid(bounds)
    lon2d, lat2d = np.meshgrid(lon, lat)
    seed = _seed("wind", view)

    if view == "Anomaly":
        u_values = _smooth_noise(lon2d.shape, seed) * 3.0
        v_values = _smooth_noise(lon2d.shape, seed + 1) * 2.0
    else:
        # North-easterly trades weakening toward the equator.
        strength = 4.0 + 4.0 * np.clip((lat2d - 1.0) / 6.0, 0, 1)
        u_values = -strength + _smooth_noise(lon2d.shape, seed) * 1.5
        v_values = -0.25 * strength + _smooth_noise(lon2d.shape, seed + 1) * 1.2

    u = _dataarray(u_values, lon, lat, "m/s", view)
    v = _dataarray(v_values, lon, lat, "m/s", view)
    speed = np.hypot(u, v)
    speed.attrs["units"] = "m/s"
    speed.attrs["view"] = view
    valid_start, valid_end = _valid_period(1)
    metadata = {
        "source": "Demo data generator",
        "product": "Wind",
        "view": view,
        "unit": "m/s",
        "valid_start": valid_start,
        "valid_end": valid_end,
        "note": "Synthetic field for interface testing; not a forecast.",
    }
    return speed, u, v, metadata
