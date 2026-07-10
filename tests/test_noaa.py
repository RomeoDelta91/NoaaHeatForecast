import io

import numpy as np
import pytest
import xarray as xr

from heat_dashboard.config import HEAT_PRODUCTS, PERCENTILE_THRESHOLDS
from heat_dashboard.noaa import (
    NOAADataError,
    dataarray_to_netcdf_bytes,
    filename_matches,
    normalize_coordinates,
    parse_listing,
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


def test_product_url_candidates_distinguish_threshold_types():
    product = HEAT_PRODUCTS["Maximum temperature (Tmax)"]
    fixed = product.url_candidates(1, 35)
    percentile = product.url_candidates(2, 90)
    assert fixed and all("wk1" in url for url in fixed)
    assert any("ge35" in url for url in fixed)
    assert percentile and all("wk2" in url for url in percentile)
    assert any("p90" in url for url in percentile)
    assert any("/percentile/" in url for url in percentile)
    assert 90 in PERCENTILE_THRESHOLDS


def test_parse_listing_extracts_netcdf_names():
    html = """
    <html><body><h1>Index of /International/global_heat</h1><pre>
    <a href="?C=N;O=D">Name</a>
    <a href="/International/">Parent Directory</a>
    <a href="tmax_ge35c_wk1.nc">tmax_ge35c_wk1.nc</a> 10-Jul-2026 06:12 2.1M
    <a href="tmax_ge35c_wk2.nc">tmax_ge35c_wk2.nc</a>
    <a href="readme.txt">readme.txt</a>
    <a href="percentile/">percentile/</a>
    </pre></body></html>
    """
    names = parse_listing(html)
    assert names == ("tmax_ge35c_wk1.nc", "tmax_ge35c_wk2.nc")


def test_filename_matches_requires_all_groups():
    groups = [("tmax",), ("wk1", "week1"), ("ge35", "35c")]
    assert filename_matches("GEFS_tmax_ge35_wk1.nc", groups)
    assert not filename_matches("tmax_ge35_wk2.nc", groups)
    assert not filename_matches("tmin_ge35_wk1.nc", groups)
    assert not filename_matches("tmax_ge35_wk1_climo.nc", groups, exclude=("climo",))


def test_resolution_falls_back_to_listing_discovery(monkeypatch):
    import heat_dashboard.noaa as noaa

    def fake_download(url):
        if url == "https://example/global_heat/GEFS_Tmax_above_35C_wk1_latest.nc":
            return b"bytes"
        raise noaa.NOAADataError(f"404 {url}")

    def fake_listing(directory):
        if directory == "https://example/global_heat/":
            return ("GEFS_Tmax_above_35C_wk1_latest.nc", "GEFS_Tmax_above_35C_wk1_climo.nc")
        return ()

    monkeypatch.setattr(noaa, "_download", fake_download)
    monkeypatch.setattr(noaa, "_directory_files", fake_listing)
    url, raw = noaa._resolve_and_download(
        ["https://example/global_heat/tmax_ge35c_wk1.nc"],
        ("https://example/global_heat/", "https://example/global_heat/percentile/"),
        [("tmax",), ("wk1",), ("ge35", "35c")],
        ("climo",),
        "test product",
    )
    assert url == "https://example/global_heat/GEFS_Tmax_above_35C_wk1_latest.nc"
    assert raw == b"bytes"

    with pytest.raises(NOAADataError, match="test product"):
        noaa._resolve_and_download(
            ["https://example/global_heat/missing.nc"],
            ("https://example/empty/",),
            [("tmax",), ("wk1",), ("ge35",)],
            (),
            "test product",
        )


def test_every_product_has_at_least_two_fixed_thresholds():
    # app.py defaults to fixed_thresholds[-2], which requires length >= 2
    for product in HEAT_PRODUCTS.values():
        assert len(product.fixed_thresholds) >= 2
