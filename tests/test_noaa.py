import io

import numpy as np
import pytest
import xarray as xr

from heat_dashboard.config import HEAT_PRODUCTS, PERCENTILE_THRESHOLDS
from heat_dashboard.noaa import (
    NOAADataError,
    dataarray_to_netcdf_bytes,
    normalize_coordinates,
)


def test_normalize_coordinates_renames_and_wraps():
    dataset = xr.Dataset(
        {"prob": (("latitude", "longitude"), np.zeros((3, 4)))},
        coords={"latitude": [5.0, 3.0, 1.0], "longitude": [300.0, 302.0, 304.0, 306.0]},
    )
    result = normalize_coordinates(dataset)
    assert "lat" in result.coords and "lon" in result.coords
    assert float(result["lon"].max()) <= 180.0
    assert list(result["lat"].values) == sorted(result["lat"].values)


def test_normalize_coordinates_rejects_unknown_grid():
    dataset = xr.Dataset({"prob": (("a", "b"), np.zeros((2, 2)))})
    with pytest.raises(NOAADataError):
        normalize_coordinates(dataset)


def test_dataarray_roundtrip_through_netcdf_bytes():
    field = xr.DataArray(
        np.linspace(0, 100, 12).reshape(3, 4),
        coords={"lat": [1.0, 2.0, 3.0], "lon": [-58.0, -57.0, -56.0, -55.0]},
        dims=("lat", "lon"),
        attrs={"units": "%"},
    )
    raw = dataarray_to_netcdf_bytes(field, "probability")
    assert isinstance(raw, bytes) and len(raw) > 0
    with xr.open_dataset(io.BytesIO(raw)) as restored:
        assert "probability" in restored
        assert np.allclose(restored["probability"].values, field.values, atol=1e-4)


def test_product_urls_distinguish_threshold_types():
    product = HEAT_PRODUCTS["Maximum temperature (Tmax)"]
    fixed_url = product.url(1, 35)
    percentile_url = product.url(2, 90)
    assert "ge35c" in fixed_url and "wk1" in fixed_url
    assert "p90" in percentile_url and "wk2" in percentile_url
    assert 90 in PERCENTILE_THRESHOLDS


def test_every_product_has_at_least_two_fixed_thresholds():
    # app.py defaults to fixed_thresholds[-2], which requires length >= 2
    for product in HEAT_PRODUCTS.values():
        assert len(product.fixed_thresholds) >= 2
