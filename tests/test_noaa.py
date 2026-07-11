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


def test_product_urls_follow_documented_pattern():
    product = HEAT_PRODUCTS["Maximum temperature (Tmax)"]
    assert product.url_candidates(1, 35) == [
        "https://ftp.cpc.ncep.noaa.gov/International/PREPARE_africa/subseasonal/realtime/data/wk1_tmax35_c3.nc"
    ]
    assert product.url_candidates(2, 90) == [
        "https://ftp.cpc.ncep.noaa.gov/International/PREPARE_africa/subseasonal/realtime/data/wk2_tmax90_c3.nc"
    ]
    assert product.climatology_url_candidates(1, 90) == [
        "https://ftp.cpc.ncep.noaa.gov/International/PREPARE_africa/subseasonal/realtime/data/wk1_tmaxclimo90.nc"
    ]
    assert 90 in PERCENTILE_THRESHOLDS


def test_documented_examples_from_reference_document():
    # Examples straight from the NOAA data-sources document.
    base = "https://ftp.cpc.ncep.noaa.gov/International/PREPARE_africa/subseasonal/realtime/data/"
    assert HEAT_PRODUCTS["Maximum heat index"].url_candidates(2, 35) == [base + "wk2_himax35_c3.nc"]
    assert HEAT_PRODUCTS["Minimum temperature (Tmin)"].url_candidates(1, 29) == [base + "wk1_tmin29_c3.nc"]
    assert HEAT_PRODUCTS["Minimum temperature (Tmin)"].climatology_url_candidates(1, 90) == [base + "wk1_tminclimo90.nc"]
    prefixes = {product.prefix for product in HEAT_PRODUCTS.values()}
    assert prefixes == {"tmax", "tmin", "himax", "himin", "hybmax", "hybmin"}


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


def test_filename_matches_documented_naming():
    exclude = ("climo", "clim", "anom")
    fixed_groups = [("tmax",), ("wk1",), ("tmax35", "ge35", "35c")]
    assert filename_matches("wk1_tmax35_c3.nc", fixed_groups, exclude)
    assert not filename_matches("wk1_tmax90_c3.nc", fixed_groups, exclude)
    assert not filename_matches("wk2_tmax35_c3.nc", fixed_groups, exclude)

    climo_groups = [("tmin",), ("wk1",), ("climo90", "p90", "90"), ("climo", "clim", "thresh")]
    assert filename_matches("wk1_tminclimo90.nc", climo_groups)
    assert not filename_matches("wk1_tmin90_c3.nc", climo_groups)


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


def test_load_heat_probability_pipeline_with_mocked_download(monkeypatch):
    """End-to-end loader test: only the HTTP download is mocked.

    The synthetic file mimics a NOAA grid: 0-360 longitudes, descending
    latitudes, an extra time dimension, and fractional probabilities.
    """
    import heat_dashboard.noaa as noaa
    from heat_dashboard.config import SURINAME_BOUNDS

    lon = np.arange(300.0, 308.0, 1.0)  # 300-307 °E == -60..-53 °W
    lat = np.arange(8.0, -1.0, -1.0)
    data = np.random.default_rng(7).uniform(0, 1, (1, lat.size, lon.size))
    dataset = xr.Dataset(
        {"prob": (("time", "latitude", "longitude"), data.astype("float32"))},
        coords={"time": [0], "latitude": lat, "longitude": lon},
    )
    raw = bytes(dataset.to_netcdf())

    requested = {}

    def fake_download(url):
        requested["url"] = url
        return raw

    monkeypatch.setattr(noaa, "_download", fake_download)
    product = HEAT_PRODUCTS["Maximum temperature (Tmax)"]
    field, metadata, payload = noaa.load_heat_probability(product, 1, 35, SURINAME_BOUNDS)

    assert requested["url"].endswith("/PREPARE_africa/subseasonal/realtime/data/wk1_tmax35_c3.nc")
    assert payload == raw
    assert metadata["filename"] == "wk1_tmax35_c3.nc"
    assert float(field["lon"].min()) >= SURINAME_BOUNDS[0]
    assert float(field["lon"].max()) <= SURINAME_BOUNDS[1]
    values = field.values
    assert np.isfinite(values).any()
    assert np.nanmax(values) <= 100.0 and np.nanmax(values) > 1.5  # rescaled to percent


def test_context_and_wind_urls_follow_documented_pattern():
    from heat_dashboard.config import (
        CONTEXT_PRODUCTS,
        context_filename,
        context_url,
        wind_filenames,
    )

    base = "https://ftp.cpc.ncep.noaa.gov/International/PREPARE_africa/subseasonal/realtime/data/"
    # Examples straight from the supplied links.
    assert context_url(context_filename("mslp", "Average", 1)) == base + "wk1_mslpt.nc"
    assert context_url(context_filename("mslp", "Anomaly", 1)) == base + "wk1_mslpa.nc"
    assert context_url(context_filename("hgt500", "Average", 1)) == base + "wk1_hgt500t.nc"
    assert context_url(context_filename("hgt500", "Anomaly", 1)) == base + "wk1_hgt500a.nc"
    assert context_url(context_filename("t2m", "Average", 1)) == base + "wk1_t2mt.nc"
    assert context_url(context_filename("t2m", "Anomaly", 1)) == base + "wk1_t2ma.nc"
    assert wind_filenames(850, "Average", 1) == ("wk1_u850t.nc", "wk1_v850t.nc")
    assert wind_filenames(850, "Anomaly", 1) == ("wk1_u850a.nc", "wk1_v850a.nc")
    assert wind_filenames(10, "Average", 2) == ("wk2_u10mt.nc", "wk2_v10mt.nc")
    assert CONTEXT_PRODUCTS["500-hPa geopotential height"].variable == "hgt500"
    # No climatology files exist: every product derives it as mean - anomaly.
    for product in CONTEXT_PRODUCTS.values():
        assert "Climatology" not in product.views


def test_wind_climatology_is_mean_minus_anomaly(monkeypatch):
    import heat_dashboard.noaa as noaa
    from heat_dashboard.config import SURINAME_BOUNDS

    def fake_component(component, level, view, week, bounds):
        value = {"Average": 8.0, "Anomaly": 2.0}[view] * (1 if component == "u" else 0.5)
        field = xr.DataArray(
            np.full((3, 3), value, dtype="float32"),
            coords={"lat": [3.0, 4.0, 5.0], "lon": [-57.0, -56.0, -55.0]},
            dims=("lat", "lon"),
        )
        return field, f"https://example/wk1_{component}850{'t' if view == 'Average' else 'a'}.nc"

    monkeypatch.setattr(noaa, "_load_wind_component", fake_component)
    speed, u, v, metadata = noaa.load_wind_field(850, "Climatology", 1, SURINAME_BOUNDS)
    assert float(u.values.mean()) == 6.0  # 8 - 2
    assert float(v.values.mean()) == 3.0  # 4 - 1
    assert len(metadata["url"]) == 4


def test_every_product_has_at_least_two_fixed_thresholds():
    # app.py defaults to fixed_thresholds[-2], which requires length >= 2
    for product in HEAT_PRODUCTS.values():
        assert len(product.fixed_thresholds) >= 2
